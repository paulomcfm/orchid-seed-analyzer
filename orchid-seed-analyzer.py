# -*- coding: utf-8 -*-
import sys
import os
import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QListWidget, QLabel, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem, QMessageBox,
    QSizePolicy, QSplitter, QTextEdit, QListWidgetItem, QGraphicsItem
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QAction
from PyQt6.QtCore import Qt, QRectF, QPointF, QSize, QSizeF

from PIL import Image
import pandas as pd
import traceback # Para imprimir exceções detalhadas

Image.MAX_IMAGE_PIXELS = None

# --- Configuration ---
# Medidas em PIXELS na imagem ORIGINAL de alta resolução
TARGET_RECT_WIDTH_ORIGINAL = 5676 
TARGET_RECT_HEIGHT_ORIGINAL = 1892 
# --- End Configuration ---


# --- Custom QGraphicsRectItem to constrain movement ---
class ConstrainedRectItem(QGraphicsRectItem):
    """ Um QGraphicsRectItem que só pode ser movido dentro de limites definidos. """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.boundary_rect = QRectF()

    def setBoundary(self, rect: QRectF):
        """Define o retângulo (em coordenadas da cena) dentro do qual este item pode se mover."""
        self.boundary_rect = rect

    def itemChange(self, change, value):
        """Chamado quando o item muda, usado para restringir a posição."""
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            new_pos = value # A nova posição proposta (QPointF)
            rect = self.rect() # A geometria do próprio retângulo (largura, altura)
            if not self.boundary_rect.isValid(): return new_pos
            rect_width = max(0.0, rect.width()); rect_height = max(0.0, rect.height())
            min_x = self.boundary_rect.left(); max_x = self.boundary_rect.right() - rect_width
            min_y = self.boundary_rect.top(); max_y = self.boundary_rect.bottom() - rect_height
            clamped_x = max(min_x, min(new_pos.x(), max_x))
            clamped_y = max(min_y, min(new_pos.y(), max_y))
            return QPointF(clamped_x, clamped_y)
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event):
        """Muda o cursor ao passar o mouse sobre."""
        QApplication.instance().setOverrideCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """Restaura o cursor ao tirar o mouse de cima."""
        QApplication.instance().restoreOverrideCursor()
        super().hoverLeaveEvent(event)

# --- Modified Graphics View ---
class PlacementView(QGraphicsView):
    """ Visualização gráfica para exibir a imagem e o retângulo móvel."""
    def __init__(self, parent=None):
        super().__init__(parent); self._scene = QGraphicsScene(self); self.setScene(self._scene)
        self.pixmap_item = None; self.rect_item = None; self.current_scale_factor = 1.0
        self.original_image_size = QSize(); self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag) # Permite arrastar a imagem

    def set_image(self, pixmap_original: QPixmap):
        """Define a imagem a ser exibida e cria o retângulo inicial."""
        try:
            self._scene.clear(); self.rect_item = None; self.pixmap_item = None
            if pixmap_original.isNull(): print("PlacementView.set_image: Warning - Received null pixmap."); return
            self.original_image_size = pixmap_original.size()
            view_rect = self.viewport().rect()
            if view_rect.width() <= 0 or view_rect.height() <= 0: view_rect.setSize(QSize(400, 300))
            img_rect = QRectF(QPointF(0, 0), QSizeF(pixmap_original.size()))
            if img_rect.isEmpty() or img_rect.width() <= 0 or img_rect.height() <= 0 :
                 self.current_scale_factor = 1.0; scaled_pixmap = pixmap_original
            else:
                scale_x = view_rect.width() / img_rect.width(); scale_y = view_rect.height() / img_rect.height()
                self.current_scale_factor = max(0.001, min(scale_x, scale_y, 1.0))
                scaled_width = max(1, int(img_rect.width() * self.current_scale_factor))
                scaled_height = max(1, int(img_rect.height() * self.current_scale_factor))
                scaled_pixmap = pixmap_original.scaled(scaled_width, scaled_height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.pixmap_item = QGraphicsPixmapItem(scaled_pixmap); self._scene.addItem(self.pixmap_item)
            scene_rect = self.pixmap_item.boundingRect(); self.setSceneRect(scene_rect)
            if scene_rect.isValid(): self.create_initial_rectangle(scene_rect)
            else: print("PlacementView.set_image: Error - Invalid boundary rect.")
        except Exception as e: print(f"PlacementView.set_image: EXCEPTION: {e}"); traceback.print_exc()
                
    def create_initial_rectangle(self, boundary: QRectF):
         """Cria o retângulo delimitador inicial (ConstrainedRectItem)."""
         if self.rect_item: self._scene.removeItem(self.rect_item)
         self.rect_item = None
         if self.current_scale_factor <= 0: return
         scaled_width = TARGET_RECT_WIDTH_ORIGINAL * self.current_scale_factor
         scaled_height = TARGET_RECT_HEIGHT_ORIGINAL * self.current_scale_factor
         scaled_width = max(1.0, scaled_width); scaled_height = max(1.0, scaled_height)
         self.rect_item = ConstrainedRectItem(0, 0, scaled_width, scaled_height) # <<< Usando ConstrainedRectItem
         self.rect_item.setBoundary(boundary)
         pen = QPen(QColor("red"), 1); pen.setCosmetic(True)
         self.rect_item.setPen(pen); self.rect_item.setZValue(1)
         self._scene.addItem(self.rect_item)
         self.rect_item.setPos(boundary.left(), boundary.top()) # Posiciona no topo-esquerdo

    def show_existing_roi(self, roi_original: tuple):
        """Cria e posiciona o retângulo com base em coordenadas originais salvas."""
        if not self.pixmap_item or not roi_original or self.current_scale_factor <= 0: return
        try:
            ox, oy, ow, oh = roi_original
            scaled_x = ox * self.current_scale_factor; scaled_y = oy * self.current_scale_factor
            scaled_w = ow * self.current_scale_factor; scaled_h = oh * self.current_scale_factor
            scaled_w = max(1.0, scaled_w); scaled_h = max(1.0, scaled_h)
            boundary = self.pixmap_item.boundingRect()
            if not boundary.isValid(): return
            if self.rect_item: self._scene.removeItem(self.rect_item)
            self.rect_item = ConstrainedRectItem(0, 0, scaled_w, scaled_h) # <<< Usando ConstrainedRectItem
            self.rect_item.setBoundary(boundary)
            pen = QPen(QColor("blue"), 1); pen.setCosmetic(True) # Azul para ROI salvo
            self.rect_item.setPen(pen); self.rect_item.setZValue(1)
            self._scene.addItem(self.rect_item)
            clamped_x = max(boundary.left(), min(scaled_x, boundary.right() - scaled_w))
            clamped_y = max(boundary.top(), min(scaled_y, boundary.bottom() - scaled_h))
            self.rect_item.setPos(clamped_x, clamped_y)
        except Exception as e: print(f"PlacementView.show_existing_roi: EXCEPTION: {e}"); traceback.print_exc()

    def get_roi_original_coords(self) -> tuple | None:
        """Obtém as coordenadas (x, y, w, h) do retângulo na escala da imagem original."""
        if self.rect_item and self.pixmap_item and self.current_scale_factor > 0 and self.original_image_size.isValid():
            try:
                scaled_top_left = self.rect_item.scenePos()
                original_x = scaled_top_left.x() / self.current_scale_factor
                original_y = scaled_top_left.y() / self.current_scale_factor
                width = TARGET_RECT_WIDTH_ORIGINAL; height = TARGET_RECT_HEIGHT_ORIGINAL
                if width <= 0 or height <= 0: print("PlacementView.get_roi_original_coords: Error - Target dimensions invalid."); return None
                max_x = self.original_image_size.width() - width; max_y = self.original_image_size.height() - height
                original_x = max(0.0, min(original_x, max_x)); original_y = max(0.0, min(original_y, max_y))
                return (original_x, original_y, width, height)
            except Exception as e: print(f"PlacementView.get_roi_original_coords: EXCEPTION: {e}"); traceback.print_exc(); return None
        else: return None

# --- Main Application Window ---
class SeedAnalyzerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Delimitador de Sementes"); self.setGeometry(100, 100, 1100, 650)
        self.image_paths = []; self.image_data = {}; self.current_image_path = None; self.export_data_df = None
        # UI Elements Setup...
        central_widget = QWidget(); self.setCentralWidget(central_widget); main_layout = QHBoxLayout(central_widget); splitter = QSplitter(Qt.Orientation.Horizontal)
        left_panel_widget = QWidget(); left_layout = QVBoxLayout(left_panel_widget); self.btn_load_files = QPushButton("Selecionar Arquivos"); self.btn_load_folder = QPushButton("Selecionar Pasta")
        self.list_widget_files = QListWidget(); self.list_widget_files.setToolTip("Clique para selecionar, [D] indica delimitado")
        self.btn_delimit = QPushButton("Confirmar Delimitação"); self.btn_delimit.setToolTip("Salva a posição atual do retângulo")
        left_layout.addWidget(self.btn_load_files); left_layout.addWidget(self.btn_load_folder); left_layout.addWidget(QLabel("Imagens Carregadas:")); left_layout.addWidget(self.list_widget_files); left_layout.addWidget(self.btn_delimit)
        splitter.addWidget(left_panel_widget)
        center_panel_widget = QWidget(); center_layout = QVBoxLayout(center_panel_widget); self.image_view = PlacementView(); center_layout.addWidget(self.image_view); splitter.addWidget(center_panel_widget)
        right_panel_widget = QWidget(); right_layout = QVBoxLayout(right_panel_widget); self.details_label = QLabel("Detalhes:"); self.details_text = QTextEdit(); self.details_text.setReadOnly(True)
        self.btn_export = QPushButton("Exportar Coordenadas"); right_layout.addWidget(self.details_label); right_layout.addWidget(self.details_text); right_layout.addStretch(); right_layout.addWidget(self.btn_export); splitter.addWidget(right_panel_widget)
        main_layout.addWidget(splitter); splitter.setSizes([250, 600, 250])
        # Connections...
        self.btn_load_files.clicked.connect(self.load_files); self.btn_load_folder.clicked.connect(self.load_folder)
        self.list_widget_files.currentItemChanged.connect(self.display_selected_image) # <<< REATIVADO
        self.btn_delimit.clicked.connect(self.confirm_delimit); self.btn_export.clicked.connect(self.export_coordinates)
        # Initial State...
        self.btn_delimit.setEnabled(False); self.btn_export.setEnabled(False); self.statusBar().showMessage("Pronto.")

    # --- Slots ---
    def load_files(self):
        files, _ = QFileDialog.getOpenFileNames( self, "Selecionar Arquivos de Imagem", "", "Arquivos de Imagem (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)" )
        if files: self.process_selected_paths(files)
    def load_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecionar Pasta com Imagens")
        if folder: files = []; valid_extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')
        for filename in os.listdir(folder):
             if filename.lower().endswith(valid_extensions): files.append(os.path.join(folder, filename))
        if files: self.process_selected_paths(files)
        else: QMessageBox.warning(self, "Aviso", "Nenhuma imagem encontrada na pasta selecionada.")
    def process_selected_paths(self, paths):
        self.image_paths = sorted(paths); self.image_data = {}; self.list_widget_files.clear()
        self.image_view._scene.clear(); self.details_text.clear(); self.current_image_path = None
        self.btn_delimit.setEnabled(False); self.btn_export.setEnabled(False); self.export_data_df = None
        progress_counter = 0; total_files = len(self.image_paths)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for path in self.image_paths:
                progress_counter += 1; QApplication.processEvents(); base_name = os.path.basename(path)
                self.statusBar().showMessage(f"Carregando {progress_counter}/{total_files}: {base_name}")
                try:
                    pil_img = Image.open(path); pil_img.load(); original_size = QSize(pil_img.width, pil_img.height); pil_img_rgb = pil_img.convert('RGB')
                    self.image_data[path] = { 'pil_image_rgb': pil_img_rgb, 'original_size': original_size, 'roi': None }; item = QListWidgetItem(base_name); self.list_widget_files.addItem(item)
                except Exception as e:
                    print(f"Erro ao carregar {path}: {e}"); self.statusBar().showMessage(f"Erro ao carregar {base_name}", 5000)
                    QMessageBox.warning(self, "Erro de Carga", f"Não foi possível carregar a imagem:\n{path}\n\nErro: {e}")
                    item = QListWidgetItem(f"{base_name} [ERRO CARREGAMENTO]"); item.setForeground(QColor("red")); self.list_widget_files.addItem(item)
        finally: QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(f"{total_files} imagens carregadas.", 5000)
        if self.list_widget_files.count() > 0: # <<< REATIVADO: Auto-seleção >>>
            first_valid_row = -1
            for i in range(self.list_widget_files.count()):
                 list_item = self.list_widget_files.item(i)
                 if list_item and list_item.text() and not "[ERRO" in list_item.text(): first_valid_row = i; break
            if first_valid_row != -1: self.list_widget_files.setCurrentRow(first_valid_row)

    def display_selected_image(self, current_item: QListWidgetItem | None, previous_item: QListWidgetItem | None):
        if not current_item or not current_item.text():
            self.image_view._scene.clear(); self.details_text.setText("Selecione uma imagem.")
            self.current_image_path = None; self.btn_delimit.setEnabled(False); return
        if "[ERRO" in current_item.text():
            self.image_view._scene.clear(); self.details_text.setText("Erro ao carregar esta imagem.")
            self.current_image_path = None; self.btn_delimit.setEnabled(False); return

        filename = current_item.text().replace(" [D]", "")
        path = next((p for p in self.image_data if os.path.basename(p) == filename), None)
        if path and path in self.image_data:
            self.current_image_path = path; img_data = self.image_data[path]; pil_img_rgb = img_data.get('pil_image_rgb')
            if not pil_img_rgb: QMessageBox.critical(self, "Erro Interno", f"Dados da imagem não encontrados para {filename}"); return
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                width = pil_img_rgb.width; height = pil_img_rgb.height; np_array = np.array(pil_img_rgb, dtype=np.uint8)
                if not np_array.flags['C_CONTIGUOUS']: np_array = np.ascontiguousarray(np_array)
                if np_array.ndim != 3 or np_array.shape[2] != 3: raise ValueError(f"NumPy shape error: {np_array.shape}")
                bytes_per_line = width * 3; q_img = QImage(np_array.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
                q_img_copy = q_img.copy()
                if q_img_copy.isNull(): raise ValueError("Failed QImage creation.")
                pixmap = QPixmap.fromImage(q_img_copy)
                if pixmap.isNull(): raise ValueError("Failed QPixmap creation.")
                self.image_view.set_image(pixmap) # Exibe imagem e cria rect inicial
                self.btn_delimit.setEnabled(True)
                roi_data = img_data.get('roi') # Mostra ROI existente
                if roi_data: self.image_view.show_existing_roi(roi_data)
                self.update_details_text()
            except Exception as e:
                 print(f"display_selected_image: EXCEPTION: {e}"); traceback.print_exc()
                 self.statusBar().showMessage(f"Erro ao exibir {filename}", 5000); QMessageBox.critical(self, "Erro de Exibição", f"Não foi possível processar/exibir imagem:\n{filename}\n\nErro: {e}")
                 self.image_view._scene.clear(); self.details_text.setText(f"Erro ao exibir:\n{filename}\n{e}"); self.current_image_path = None; self.btn_delimit.setEnabled(False)
            finally: QApplication.restoreOverrideCursor()
        else:
            self.image_view._scene.clear(); self.details_text.setText(f"Erro interno: Dados não encontrados para\n{filename}"); self.current_image_path = None; self.btn_delimit.setEnabled(False)

    def keyPressEvent(self, event):
        """Handle key press events for the main window."""
        # Check if Enter/Return was pressed
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            # Only process if we have a non-delimited image selected
            current_item = self.list_widget_files.currentItem()
            if (current_item and 
                self.current_image_path and 
                not "[ERRO" in current_item.text() and 
                not current_item.text().endswith(" [D]")):
                # Call the same method that the button uses
                self.confirm_delimit()
            return
        # For other keys, use the default handler
        super().keyPressEvent(event)

    def confirm_delimit(self):
        if not self.current_image_path or not self.image_view.rect_item: QMessageBox.warning(self, "Aviso", "Carregue e exiba uma imagem e certifique-se que o retângulo está visível."); return
        roi_original = self.image_view.get_roi_original_coords()
        if not roi_original: QMessageBox.warning(self, "Aviso", "Não foi possível obter coordenadas do retângulo."); return
        self.image_data[self.current_image_path]['roi'] = roi_original; current_row = self.list_widget_files.currentRow()
        if current_row >= 0:
            item = self.list_widget_files.item(current_row)
            if item and item.text() and not item.text().endswith(" [D]") and not "[ERRO" in item.text(): item.setText(item.text() + " [D]")
        self.update_details_text()
        pen = QPen(QColor("blue"), 1); pen.setCosmetic(True) # Muda para azul
        if self.image_view.rect_item: self.image_view.rect_item.setPen(pen)
        any_delimited = any(data.get('roi', None) is not None for data in self.image_data.values()); self.btn_export.setEnabled(any_delimited)
        # Auto-advance logic...
        next_row = -1; start_row = current_row if current_row >= 0 else -1
        if start_row != -1:
            for i in range(start_row + 1, self.list_widget_files.count()):
                list_item = self.list_widget_files.item(i)
                if list_item and list_item.text() and not "[ERRO" in list_item.text() and not list_item.text().endswith(" [D]"): next_row = i; break
            if next_row == -1:
                for i in range(start_row):
                    list_item = self.list_widget_files.item(i)
                    if list_item and list_item.text() and not "[ERRO" in list_item.text() and not list_item.text().endswith(" [D]"): next_row = i; break
            if next_row != -1: self.list_widget_files.setCurrentRow(next_row)
            else:
                all_done = True
                for i in range(self.list_widget_files.count()):
                    list_item = self.list_widget_files.item(i)
                    if list_item and list_item.text() and not "[ERRO" in list_item.text() and not list_item.text().endswith(" [D]"): all_done = False; break
                if all_done: QMessageBox.information(self,"Informação", "Todas as imagens válidas foram delimitadas.")

    def update_details_text(self):
        if not self.current_image_path or self.current_image_path not in self.image_data: self.details_text.clear(); return
        path = self.current_image_path; img_data = self.image_data[path]; filename = os.path.basename(path); original_size = img_data.get('original_size', QSize(0,0)); roi = img_data.get('roi', None)
        details = f"Arquivo: {filename}\n";
        if original_size.isValid(): details += f"Dimensões Originais: {original_size.width()} x {original_size.height()} px\n"
        else: details += "Dimensões Originais: (inválido)\n"
        details += f"Status: {'Delimitado' if roi else 'Aguardando delimitação'}\n\n"
        if roi:
            if isinstance(roi, tuple) and len(roi) == 4:
                details += "Coordenadas ROI (Imagem Original):\n"; details += f"  X: {roi[0]:.3f} px\n"; details += f"  Y: {roi[1]:.3f} px\n";
                details += f"  Largura: {roi[2]:.3f} px\n"; details += f"  Altura: {roi[3]:.3f} px\n"
            else: details += "Coordenadas ROI: (Formato inválido)\n"
        self.details_text.setText(details)

    def export_coordinates(self):
        export_list = []
        for path in self.image_paths:
             if path in self.image_data:
                 data = self.image_data[path]
                 if data.get('roi', None):
                     roi = data['roi']
                     if isinstance(roi, tuple) and len(roi) == 4: export_list.append({ 'filename': os.path.basename(path), 'roi_x_original': roi[0], 'roi_y_original': roi[1], 'roi_width_original': roi[2], 'roi_height_original': roi[3] })
                     else: print(f"Warning: Skipping export for {os.path.basename(path)} due to invalid ROI data: {roi}")
        if not export_list: QMessageBox.warning(self, "Exportar", "Nenhuma coordenada válida definida."); return
        self.export_data_df = pd.DataFrame(export_list); fileName, selectedFilter = QFileDialog.getSaveFileName( self, "Salvar Coordenadas Delimitadas", "", "Arquivo Excel (*.xlsx);;Arquivo CSV (*.csv)" )
        if fileName:
            try:
                if selectedFilter == "Arquivo Excel (*.xlsx)" and not fileName.lower().endswith('.xlsx'): fileName += '.xlsx'
                elif selectedFilter == "Arquivo CSV (*.csv)" and not fileName.lower().endswith('.csv'): fileName += '.csv'
                if fileName.lower().endswith('.xlsx'): self.export_data_df.to_excel(fileName, index=False, engine='openpyxl', float_format="%.3f")
                elif fileName.lower().endswith('.csv'): self.export_data_df.to_csv(fileName, index=False, encoding='utf-8-sig', float_format="%.3f")
                QMessageBox.information(self, "Exportar", f"Coordenadas exportadas com sucesso para:\n{fileName}")
            except Exception as e: print(f"Erro ao exportar dados: {e}"); self.statusBar().showMessage(f"Erro ao exportar para {fileName}", 5000); QMessageBox.critical(self, "Erro de Exportação", f"Não foi possível salvar o arquivo:\n{e}")

# --- Main Execution ---
if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_window = SeedAnalyzerApp()
    main_window.showMaximized()  
    sys.exit(app.exec())