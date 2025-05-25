# -*- coding: utf-8 -*-
import sys
import os
import random
import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QListWidget, QLabel, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem, QMessageBox,
    QSizePolicy, QSplitter, QTextEdit, QListWidgetItem, QGraphicsItem,
    QLineEdit
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QDoubleValidator, QIntValidator
from PyQt6.QtCore import Qt, QRectF, QPointF, QSize, QSizeF
from PIL import Image
import traceback
import csv
from datetime import datetime

# --- Configuration ---
TARGET_RECT_WIDTH_ORIGINAL = 5676
TARGET_RECT_HEIGHT_ORIGINAL = 1892
TILE_COLS = 6
TILE_ROWS = 2
# --- End Configuration ---

class ConstrainedRectItem(QGraphicsRectItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.boundary_rect = QRectF()

    def setBoundary(self, rect: QRectF):
        self.boundary_rect = rect

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            new_pos = value
            rect = self.rect()
            if not self.boundary_rect.isValid():
                return new_pos
            w, h = rect.width(), rect.height()
            min_x = self.boundary_rect.left()
            max_x = self.boundary_rect.right() - w
            min_y = self.boundary_rect.top()
            max_y = self.boundary_rect.bottom() - h
            x = max(min_x, min(new_pos.x(), max_x))
            y = max(min_y, min(new_pos.y(), max_y))
            return QPointF(x, y)
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event):
        QApplication.instance().setOverrideCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        QApplication.instance().restoreOverrideCursor()
        super().hoverLeaveEvent(event)

class PlacementView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.pixmap_item = None
        self.rect_item = None
        self.current_scale_factor = 1.0
        self.original_image_size = QSize()
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def set_image(self, pixmap_original: QPixmap):
        try:
            self._scene.clear()
            self.rect_item = None
            self.pixmap_item = None
            if pixmap_original.isNull():
                return
            self.original_image_size = pixmap_original.size()
            view_rect = self.viewport().rect()
            if view_rect.width() <= 0 or view_rect.height() <= 0:
                view_rect.setSize(QSize(400, 300))
            img_rect = QRectF(QPointF(0, 0), QSizeF(pixmap_original.size()))
            scale_x = view_rect.width() / img_rect.width()
            scale_y = view_rect.height() / img_rect.height()
            factor = max(0.001, min(scale_x, scale_y, 1.0))
            sw = max(1, int(img_rect.width() * factor))
            sh = max(1, int(img_rect.height() * factor))
            scaled = pixmap_original.scaled(sw, sh, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.current_scale_factor = factor
            self.pixmap_item = QGraphicsPixmapItem(scaled)
            self._scene.addItem(self.pixmap_item)
            scene_rect = self.pixmap_item.boundingRect()
            self.setSceneRect(scene_rect)
            self.create_initial_rectangle(scene_rect)
        except Exception as e:
            print(f"PlacementView.set_image error: {e}")
            traceback.print_exc()

    def create_initial_rectangle(self, boundary: QRectF):
        if self.rect_item:
            self._scene.removeItem(self.rect_item)
        w = TARGET_RECT_WIDTH_ORIGINAL * self.current_scale_factor
        h = TARGET_RECT_HEIGHT_ORIGINAL * self.current_scale_factor
        w, h = max(1.0, w), max(1.0, h)
        self.rect_item = ConstrainedRectItem(0, 0, w, h)
        self.rect_item.setBoundary(boundary)
        pen = QPen(QColor("red"), 1)
        pen.setCosmetic(True)
        self.rect_item.setPen(pen)
        self.rect_item.setZValue(1)
        self._scene.addItem(self.rect_item)
        self.rect_item.setPos(boundary.left(), boundary.top())

    def get_roi_original_coords(self) -> tuple | None:
        if not self.rect_item:
            return None
        pos = self.rect_item.scenePos()
        ox, oy = pos.x() / self.current_scale_factor, pos.y() / self.current_scale_factor
        w, h = TARGET_RECT_WIDTH_ORIGINAL, TARGET_RECT_HEIGHT_ORIGINAL
        return (max(0, min(ox, self.original_image_size.width() - w)),
                max(0, min(oy, self.original_image_size.height() - h)), w, h)

    def show_existing_roi(self, roi):
        if not self.pixmap_item:
            return
        orig_x, orig_y, _, _ = roi 
        scaled_x = orig_x * self.current_scale_factor
        scaled_y = orig_y * self.current_scale_factor
        if not self.rect_item:
            self.create_initial_rectangle(self.pixmap_item.boundingRect())
        self.rect_item.setPos(scaled_x, scaled_y)

class SeedAnalyzerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Delimitador de Sementes")
        self.resize(1200, 700)
        self.image_paths = []
        self.image_data = {}
        self.analysis_items = []
        self.analysis_stage = False
        docs = "C:\\Documentos"
        self.default_directory = docs if os.path.isdir(docs) else os.path.expanduser("~")

        central = QWidget()
        self.setCentralWidget(central)

        v_main = QVBoxLayout(central)
        v_main.setContentsMargins(0, 0, 0, 0)
        v_main.setSpacing(0)

        fields = QWidget()
        fields.setFixedHeight(24) 
        f_layout = QHBoxLayout(fields)
        f_layout.setContentsMargins(2, 0, 2, 0)
        f_layout.setSpacing(3)

        self.input_analise = QLineEdit()
        self.input_especie = QLineEdit()  
        self.input_temp = QLineEdit()
        self.input_tempo = QLineEdit()

        self.input_analise.setPlaceholderText("Digite o nome da análise")
        self.input_especie.setPlaceholderText("Digite o nome da espécie")
        self.input_temp.setPlaceholderText("Digite a temperatura em °C")
        self.input_tempo.setPlaceholderText("Digite o tempo em horas")

        for field in [self.input_analise, self.input_especie, self.input_temp, self.input_tempo]:
            field.setMaximumHeight(20)
            field.setFixedHeight(20)  

        self.input_temp.setValidator(QDoubleValidator())
        self.input_tempo.setValidator(QIntValidator())

        labels_fields = [
            ("Análise:", self.input_analise),
            ("Espécie:", self.input_especie),
            ("Temp. Armazenamento (°C):", self.input_temp),
            ("Tempo (h):", self.input_tempo)
        ]

        for label, widget in labels_fields:
            f_layout.addWidget(QLabel(label))
            f_layout.addWidget(widget)
        v_main.addWidget(fields)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget(); left.setMinimumWidth(60)
        l_layout = QVBoxLayout(left)
        self.btn_load_files = QPushButton("Selecionar Arquivos")
        self.btn_load_folder = QPushButton("Selecionar Pasta")
        self.list_widget = QListWidget()
        for w in (self.btn_load_files, self.btn_load_folder, QLabel("Itens:"), self.list_widget):
            l_layout.addWidget(w)
        splitter.addWidget(left)

        center = QWidget()
        c_layout = QVBoxLayout(center)
        self.image_view = PlacementView()
        c_layout.addWidget(self.image_view, 3)
        self.recorte_container = QWidget()
        rc_layout = QHBoxLayout(self.recorte_container)
        self.view_orig = QGraphicsView()
        self.view_orig.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view_orig.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scene_orig = QGraphicsScene(self.view_orig)
        self.view_orig.setScene(self.scene_orig)
        rc_layout.addWidget(self.view_orig, 1)
        self.view_analyzed = QGraphicsView()
        self.view_analyzed.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view_analyzed.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scene_analyzed = QGraphicsScene(self.view_analyzed)
        self.view_analyzed.setScene(self.scene_analyzed)
        rc_layout.addWidget(self.view_analyzed, 1)
        self.recorte_container.setVisible(False)
        c_layout.addWidget(self.recorte_container, 2)
        splitter.addWidget(center)

        right = QWidget(); right.setMinimumWidth(60)
        r_layout = QVBoxLayout(right)
        self.details_text = QTextEdit(); self.details_text.setReadOnly(True)
        r_layout.addWidget(self.details_text)

        self.btn_delimit = QPushButton('Delimitar [D]')
        self.btn_analyze = QPushButton('Analisar Imagens')
        self.btn_confirm = QPushButton('Confirmar [C]')
        self.btn_remove = QPushButton('Remover [R]')
        self.btn_confirm_all = QPushButton('Confirmar Todas')
        self.btn_remove_all = QPushButton('Remover Todas')
        self.btn_confirm_remaining = QPushButton('Confirmar Restantes') 
        self.btn_remove_remaining = QPushButton('Remover Restantes')   
        self.btn_confirm_report = QPushButton('Confirmar e Gerar Relatório')
        self.btn_help = QPushButton("Ajuda")

        r_layout.addWidget(self.btn_delimit)
        r_layout.addWidget(self.btn_analyze)
        r_layout.addWidget(self.btn_confirm)
        r_layout.addWidget(self.btn_remove)
        r_layout.addWidget(self.btn_confirm_all)
        r_layout.addWidget(self.btn_remove_all)
        r_layout.addWidget(self.btn_confirm_remaining) 
        r_layout.addWidget(self.btn_remove_remaining)   
        r_layout.addWidget(self.btn_confirm_report)
        
        r_layout.addStretch()
        r_layout.addWidget(self.btn_help)

        self.btn_delimit.setEnabled(False)
        self.btn_analyze.setEnabled(False)
        
        buttons_to_hide_initially = [
            self.btn_confirm, self.btn_remove, 
            self.btn_confirm_all, self.btn_remove_all,
            self.btn_confirm_remaining, self.btn_remove_remaining, 
            self.btn_confirm_report
        ]
        for btn in buttons_to_hide_initially:
            btn.setVisible(False)
        
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1); splitter.setStretchFactor(1, 16); splitter.setStretchFactor(2, 1)
        v_main.addWidget(splitter)

        self.btn_load_files.clicked.connect(self.load_files)
        self.btn_load_folder.clicked.connect(self.load_folder)
        self.list_widget.currentItemChanged.connect(self.display_selected_item)
        self.btn_delimit.clicked.connect(self.confirm_delimit)
        self.btn_analyze.clicked.connect(self.analyze_images)
        self.btn_confirm.clicked.connect(self.confirm_current_analysis)
        self.btn_remove.clicked.connect(self.remove_current_analysis)
        self.btn_confirm_all.clicked.connect(self.confirm_all)
        self.btn_remove_all.clicked.connect(self.remove_all)
        self.btn_confirm_remaining.clicked.connect(self.confirm_remaining) 
        self.btn_remove_remaining.clicked.connect(self.remove_remaining) 
        self.btn_confirm_report.clicked.connect(self.generate_report)
        self.btn_help.clicked.connect(self.show_help)

        self.statusBar().showMessage("Pronto.")

    def keyPressEvent(self, event):
        if (event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter) and \
           not self.analysis_stage and self.btn_delimit.isVisible() and self.btn_delimit.isEnabled():
            self.confirm_delimit()
        elif event.key() == Qt.Key.Key_D and event.modifiers() & Qt.KeyboardModifier.ControlModifier and \
             not self.analysis_stage and self.btn_delimit.isVisible() and self.btn_delimit.isEnabled():
            self.confirm_delimit()
        elif event.key() == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier and \
             self.analysis_stage and self.btn_confirm.isVisible() and self.btn_confirm.isEnabled():
            self.confirm_current_analysis()
        elif event.key() == Qt.Key.Key_R and event.modifiers() & Qt.KeyboardModifier.ControlModifier and \
             self.analysis_stage and self.btn_remove.isVisible() and self.btn_remove.isEnabled():
            self.remove_current_analysis()
        else:
            super().keyPressEvent(event)

    def update_details_text(self):
        if not self.analysis_stage:
            if not getattr(self, 'current_image', None): return
            data = self.image_data.get(self.current_image, {})
            basename = os.path.basename(self.current_image)
            roi = data.get('roi')
            txt = f"Arquivo: {basename}\nROI: x={roi[0]:.1f}, y={roi[1]:.1f}, w={roi[2]}, h={roi[3]}" if roi else f"Arquivo: {basename}\nROI não definida"
            self.details_text.setText(txt)
        else: # Analysis stage
            idx = self.list_widget.currentRow()
            if idx < 0 or not self.analysis_items or idx >= len(self.analysis_items):
                self.details_text.setText("Nenhum item selecionado ou lista de análise vazia.")
                return
            item = self.analysis_items[idx]
            cnt = item['counts']
            status = item['status'] or 'Aguardando'
            self.details_text.setText(
                f"Arquivo: {os.path.basename(item['recorte'])}\n"
                f"Total sementes: {cnt['total']}\nViáveis: {cnt['viable']}\nInviáveis: {cnt['inviable']}\nStatus: {status}"
            )


    def load_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Selecionar Arquivos de Imagem", self.default_directory,
                                                "Imagens (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if files:
            self.default_directory = os.path.dirname(files[0])
            self.process_selected_paths(files)

    def load_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecionar Pasta com Imagens", self.default_directory)
        if folder:
            self.default_directory = folder
            imgs = [os.path.join(folder, fn) for fn in sorted(os.listdir(folder))
                    if fn.lower().endswith(('.png','.jpg','.jpeg','.bmp','.tif','.tiff'))]
            self.process_selected_paths(imgs)

    def process_selected_paths(self, paths):
        self.analysis_stage = False
        self.input_analise.clear(); self.input_especie.clear(); self.input_temp.clear(); self.input_tempo.clear()
        self.image_paths = paths
        self.image_data.clear(); self.analysis_items.clear(); self.list_widget.clear(); self.details_text.clear()
        self.current_image = None
        self.image_view.setVisible(True); self.recorte_container.setVisible(False)
        
        self.btn_delimit.setVisible(True)
        self.btn_analyze.setVisible(False)
        self.btn_analyze.setEnabled(False) # Ensure analyze button is disabled initially
        
        buttons_to_hide = [
            self.btn_confirm, self.btn_remove, self.btn_confirm_all, self.btn_remove_all,
            self.btn_confirm_remaining, self.btn_remove_remaining, self.btn_confirm_report
        ]
        for btn in buttons_to_hide:
            btn.setVisible(False)
        
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage(f"Carregando 0 de {len(paths)} imagens...")
        QApplication.processEvents()
        
        valid_images = 0
        for i, path in enumerate(paths):
            self.statusBar().showMessage(f"Carregando {i+1} de {len(paths)} imagens...")
            QApplication.processEvents()
            try:
                pil = Image.open(path).convert('RGB')
                width, height = pil.size
                if width < TARGET_RECT_WIDTH_ORIGINAL or height < TARGET_RECT_HEIGHT_ORIGINAL:
                    itm = QListWidgetItem(f"{os.path.basename(path)} [TAMANHO INSUFICIENTE]")
                    itm.setForeground(QColor('red'))
                    self.list_widget.addItem(itm)
                    continue
                self.image_data[path] = {'pil': pil, 'roi': None, 'pixmap_display': None} # Added pixmap_display
                self.list_widget.addItem(QListWidgetItem(os.path.basename(path)))
                valid_images += 1
            except Exception as e:
                itm = QListWidgetItem(f"{os.path.basename(path)} [ERRO]")
                itm.setForeground(QColor('red'))
                self.list_widget.addItem(itm)
                print(f"Erro ao carregar {path}: {e}")

        self.statusBar().showMessage(f"Pronto. {valid_images} imagens válidas carregadas.")
        QApplication.processEvents() 
        QApplication.restoreOverrideCursor()
        
        if valid_images == 0 and paths: 
             QMessageBox.warning(self, "Aviso", 
                            "Nenhuma imagem válida foi carregada. Verifique se as imagens atendem ao tamanho mínimo de " +
                            f"{TARGET_RECT_WIDTH_ORIGINAL}x{TARGET_RECT_HEIGHT_ORIGINAL} pixels ou se não estão corrompidas.")
        elif valid_images > 0:
            first_valid_idx = -1
            for i in range(self.list_widget.count()):
                item_text = self.list_widget.item(i).text()
                if '[ERRO]' not in item_text and '[TAMANHO INSUFICIENTE]' not in item_text:
                    first_valid_idx = i
                    break
            if first_valid_idx != -1:
                 self.list_widget.setCurrentRow(first_valid_idx)
            else: # No valid images to select, clear display
                self.image_view._scene.clear()
                self.details_text.setText("Nenhuma imagem válida para exibir.")
                self.btn_delimit.setEnabled(False)

        self.update_analysis_action_buttons_state() 

    def display_selected_item(self, current, previous=None):
        if not current:
            if self.analysis_stage:
                self.scene_orig.clear(); self.scene_analyzed.clear()
            else:
                self.image_view._scene.clear()
                self.btn_delimit.setEnabled(False)
            self.update_details_text() # Will show appropriate message for no selection
            self.update_analysis_action_buttons_state()
            return

        name = current.text()
        if not self.analysis_stage:
            if '[ERRO]' in name or '[TAMANHO INSUFICIENTE]' in name:
                self.image_view._scene.clear()
                self.btn_delimit.setEnabled(False)
            else:
                path = next((p for p in self.image_data if os.path.basename(p) == name.replace(' [D]','')), None)
                if not path: return

                self.current_image = path
                data = self.image_data[path]
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                
                if data.get('pixmap_display') is None: 
                    arr = np.array(data['pil'], dtype=np.uint8)
                    h_orig, w_orig, _ = arr.shape
                    img_q = QImage(arr.data, w_orig, h_orig, w_orig*3, QImage.Format.Format_RGB888)
                    data['pixmap_display'] = QPixmap.fromImage(img_q)

                self.image_view.set_image(data['pixmap_display'])
                
                roi_data = data.get('roi')
                if roi_data:
                    self.image_view.show_existing_roi(roi_data)
                else: # Reset rect if no ROI
                    if self.image_view.pixmap_item:
                         self.image_view.create_initial_rectangle(self.image_view.pixmap_item.boundingRect())

                self.btn_delimit.setEnabled(True)
                QApplication.restoreOverrideCursor()
        else: 
            idx = self.list_widget.currentRow()
            if 0 <= idx < len(self.analysis_items):
                item = self.analysis_items[idx]
                self.scene_orig.clear(); self.scene_orig.addPixmap(QPixmap(item['recorte']))
                self.view_orig.fitInView(self.scene_orig.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
                self.scene_analyzed.clear(); self.scene_analyzed.addPixmap(QPixmap(item['analysed']))
                self.view_analyzed.fitInView(self.scene_analyzed.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            else: # Should not happen if list is populated and selection is valid
                self.scene_orig.clear(); self.scene_analyzed.clear()
        
        self.update_details_text()
        self.update_analysis_action_buttons_state()


    def confirm_delimit(self):
        if not self.current_image: return
        roi = self.image_view.get_roi_original_coords()
        if not roi:
            QMessageBox.warning(self, "Aviso", "Não foi possível obter coordenadas.")
            return
        self.image_data[self.current_image]['roi'] = roi
        itm = self.list_widget.currentItem()
        if itm and not itm.text().endswith(' [D]'):
            base_name = itm.text().replace(' [ERRO]', '').replace(' [TAMANHO INSUFICIENTE]', '')
            itm.setText(base_name + ' [D]')
        
        all_valid_delimited = True
        has_any_valid_image = False
        next_undelimited_row = -1

        for i in range(self.list_widget.count()):
            list_item = self.list_widget.item(i)
            item_text = list_item.text()
            is_error_or_small = '[ERRO]' in item_text or '[TAMANHO INSUFICIENTE]' in item_text
            
            if not is_error_or_small:
                has_any_valid_image = True
                path_key = next((p for p in self.image_data if os.path.basename(p) in item_text), None)
                if path_key and self.image_data[path_key].get('roi') is None:
                    all_valid_delimited = False
                    if next_undelimited_row == -1: # Find first undelimited
                        next_undelimited_row = i
        
        if has_any_valid_image and all_valid_delimited:
            self.btn_analyze.setVisible(True)
            self.btn_analyze.setEnabled(True)
            QMessageBox.information(self, "Info", "Todas as imagens válidas foram delimitadas. Pronto para analisar.")
        else:
            self.btn_analyze.setVisible(False)
            self.btn_analyze.setEnabled(False)

        if next_undelimited_row != -1:
            self.list_widget.setCurrentRow(next_undelimited_row)
        elif not all_valid_delimited and has_any_valid_image: # All valid images are delimited, but some might have been skipped
             pass # Stay on current or let user pick
        self.update_details_text()


    def update_report_button_state(self):
        if not self.analysis_stage or not self.analysis_items:
            self.btn_confirm_report.setEnabled(False)
            return
        all_processed = all(item['status'] in ['Confirmado', 'Removido'] for item in self.analysis_items)
        self.btn_confirm_report.setEnabled(all_processed)

    def update_analysis_action_buttons_state(self):
        if not self.analysis_stage or not self.analysis_items:
            for btn_name in ['btn_confirm', 'btn_remove', 'btn_confirm_all', 'btn_remove_all', 
                             'btn_confirm_remaining', 'btn_remove_remaining', 'btn_confirm_report']:
                if hasattr(self, btn_name):
                    getattr(self, btn_name).setEnabled(False)
            return

        has_unprocessed_items = any(item['status'] is None for item in self.analysis_items)
        
        self.btn_confirm_remaining.setEnabled(has_unprocessed_items)
        self.btn_remove_remaining.setEnabled(has_unprocessed_items)

        self.btn_confirm_all.setEnabled(bool(self.analysis_items))
        self.btn_remove_all.setEnabled(bool(self.analysis_items))

        current_row = self.list_widget.currentRow()
        # CHANGED: Enable confirm/remove if a valid item is selected, regardless of its current status
        can_process_current = (0 <= current_row < len(self.analysis_items))
            
        self.btn_confirm.setEnabled(can_process_current)
        self.btn_remove.setEnabled(can_process_current)
        
        self.update_report_button_state()

    def analyze_images(self):
        valid_image_data_for_analysis = {}
        original_paths_for_analysis = [] # Keep track of original paths for base_dir

        for path, data in self.image_data.items():
            is_valid_for_analysis = True
            list_item_text_found = ""
            for i in range(self.list_widget.count()):
                item_text_iter = self.list_widget.item(i).text()
                # Match based on basename being part of the list_widget item text
                # This is slightly fragile if basenames are substrings of others, but common for this setup
                if os.path.basename(path) in item_text_iter:
                    list_item_text_found = item_text_iter
                    break
            
            if '[ERRO]' in list_item_text_found or '[TAMANHO INSUFICIENTE]' in list_item_text_found:
                is_valid_for_analysis = False
            
            if data['roi'] is None: # Must have ROI
                is_valid_for_analysis = False

            if is_valid_for_analysis:
                valid_image_data_for_analysis[path] = data
                original_paths_for_analysis.append(path)
        
        if not valid_image_data_for_analysis:
            QMessageBox.warning(self, "Aviso", "Nenhuma imagem válida com ROI definida para análise.")
            return

        self.statusBar().showMessage("Preparando análise...")
        QApplication.processEvents()

        # Use the directory of the first original image that will be processed
        base = os.path.dirname(original_paths_for_analysis[0]) 
        out_dir = os.path.join(base, 'imagens_recortadas')
        os.makedirs(out_dir, exist_ok=True)
        self.analysis_items = []

        for path, data in valid_image_data_for_analysis.items():
            base_file = os.path.basename(path)
            # ... (rest of the cropping and analysis logic remains the same)
            ox, oy, ow, oh = map(int, data['roi'])
            tile_w = ow // TILE_COLS
            tile_h = oh // TILE_ROWS
            for idx in range(TILE_COLS * TILE_ROWS):
                row = idx // TILE_COLS
                col = idx % TILE_COLS
                left = ox + col * tile_w
                top = oy + row * tile_h

                self.statusBar().showMessage(f"Recortando imagem {base_file}: seção {idx+1}/{TILE_COLS*TILE_ROWS}...")
                QApplication.processEvents()

                crop = data['pil'].crop((left, top, left+tile_w, top+tile_h))
                base_name_no_ext = os.path.splitext(os.path.basename(path))[0]
                rec_name = f"{base_name_no_ext}_{idx+1}.png"
                rec_path = os.path.join(out_dir, rec_name)
                crop.save(rec_path)

                self.statusBar().showMessage(f"Analisando imagem {base_file}: seção {idx+1}/{TILE_COLS*TILE_ROWS}...")
                QApplication.processEvents()

                ana_name = f"{base_name_no_ext}_{idx+1}_analisada.png"
                ana_path = os.path.join(out_dir, ana_name)
                crop.save(ana_path) # Placeholder analysis
                total = random.randint(5, 15)
                viable = random.randint(0, total)
                invi = total - viable
                self.analysis_items.append({
                    'recorte': rec_path,
                    'analysed': ana_path,
                    'counts': {'total': total, 'viable': viable, 'inviable': invi},
                    'status': None
                })


        self.statusBar().showMessage("Pronto.")
        QApplication.processEvents()

        self.analysis_stage = True
        self.image_view.setVisible(False)
        self.recorte_container.setVisible(True)
        self.btn_delimit.setVisible(False)
        self.btn_analyze.setVisible(False)
        
        buttons_to_show = [
            self.btn_confirm_all, self.btn_remove_all,
            self.btn_confirm_remaining, self.btn_remove_remaining, 
            self.btn_confirm, self.btn_remove, self.btn_confirm_report
        ]
        for btn in buttons_to_show:
            btn.setVisible(True)

        self.list_widget.clear()
        for item in self.analysis_items:
            self.list_widget.addItem(os.path.basename(item['recorte']))
        
        try: self.list_widget.currentItemChanged.disconnect()
        except TypeError: pass
        self.list_widget.currentItemChanged.connect(self.display_selected_item)
        
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        else: 
            self.scene_orig.clear(); self.scene_analyzed.clear()
            self.update_details_text() # Will show no items

        self.update_analysis_action_buttons_state()
        self.activateWindow(); self.list_widget.setFocus()

    def confirm_current_analysis(self):
        idx = self.list_widget.currentRow()
        if idx < 0 or idx >= len(self.analysis_items): return
        
        # Update status even if it's already 'Confirmado'
        self.analysis_items[idx]['status'] = 'Confirmado'
        itm = self.list_widget.item(idx)
        base_name = os.path.basename(self.analysis_items[idx]['recorte'])
        # Ensure text doesn't duplicate status markers
        if " [R]" in itm.text():
            itm.setText(itm.text().replace(" [R]", " [C]"))
        elif not itm.text().endswith(" [C]"):
            itm.setText(f"{base_name} [C]")
        
        self.update_details_text() # Update details to reflect change
        self.next_analysis() # Try to move to next *unprocessed*
        self.update_analysis_action_buttons_state()


    def remove_current_analysis(self):
        idx = self.list_widget.currentRow()
        if idx < 0 or idx >= len(self.analysis_items): return

        # Update status even if it's already 'Removido'
        self.analysis_items[idx]['status'] = 'Removido'
        itm = self.list_widget.item(idx)
        base_name = os.path.basename(self.analysis_items[idx]['recorte'])
        # Ensure text doesn't duplicate status markers
        if " [C]" in itm.text():
            itm.setText(itm.text().replace(" [C]", " [R]"))
        elif not itm.text().endswith(" [R]"):
             itm.setText(f"{base_name} [R]")

        self.update_details_text() # Update details to reflect change
        self.next_analysis() # Try to move to next *unprocessed*
        self.update_analysis_action_buttons_state()

    def next_analysis(self):
        current_idx = self.list_widget.currentRow()
        # Try to find the next item with status None, starting after current
        for i in range(current_idx + 1, len(self.analysis_items)):
            if self.analysis_items[i]['status'] is None:
                self.list_widget.setCurrentRow(i)
                return
        # If not found after current, try from the beginning
        for i in range(current_idx + 1): # up to and including current_idx
            if self.analysis_items[i]['status'] is None:
                self.list_widget.setCurrentRow(i)
                return
        
        # If still no unprocessed item found, it means all are processed
        # No explicit message here, as user can still select and change
        self.update_analysis_action_buttons_state()


    def confirm_all(self):
        if not self.analysis_items: return
        for i, it in enumerate(self.analysis_items):
            it['status'] = 'Confirmado'
            list_item = self.list_widget.item(i)
            base_name = os.path.basename(it['recorte'])
            list_item.setText(f"{base_name} [C]") # Overwrite previous status
        self.update_analysis_action_buttons_state()
        self.update_details_text() # Update for current selection

    def remove_all(self):
        if not self.analysis_items: return
        for i, it in enumerate(self.analysis_items):
            it['status'] = 'Removido'
            list_item = self.list_widget.item(i)
            base_name = os.path.basename(it['recorte'])
            list_item.setText(f"{base_name} [R]") # Overwrite previous status
        self.update_analysis_action_buttons_state()
        self.update_details_text() # Update for current selection

    def confirm_remaining(self):
        if not self.analysis_items: return
        items_changed = False
        for i, item_data in enumerate(self.analysis_items):
            if item_data['status'] is None:
                item_data['status'] = 'Confirmado'
                list_item = self.list_widget.item(i)
                base_name = os.path.basename(item_data['recorte'])
                list_item.setText(f"{base_name} [C]")
                items_changed = True
        
        if items_changed:
            QMessageBox.information(self, "Info", "Todas as análises restantes foram confirmadas.")
        else:
            QMessageBox.information(self, "Info", "Nenhuma análise pendente para confirmar.")
        self.update_analysis_action_buttons_state()
        self.update_details_text()

    def remove_remaining(self):
        if not self.analysis_items: return
        items_changed = False
        for i, item_data in enumerate(self.analysis_items):
            if item_data['status'] is None:
                item_data['status'] = 'Removido'
                list_item = self.list_widget.item(i)
                base_name = os.path.basename(item_data['recorte'])
                list_item.setText(f"{base_name} [R]")
                items_changed = True

        if items_changed:
            QMessageBox.information(self, "Info", "Todas as análises restantes foram removidas.")
        else:
            QMessageBox.information(self, "Info", "Nenhuma análise pendente para remover.")
        self.update_analysis_action_buttons_state()
        self.update_details_text()

    def generate_report(self):
        try:
            required_inputs = {
                "Análise": self.input_analise.text().strip(),
                "Espécie": self.input_especie.text().strip(),
                "Temperatura": self.input_temp.text().strip(),
                "Tempo": self.input_tempo.text().strip()
            }
            empty_fields = [field for field, value in required_inputs.items() if not value]
            if empty_fields:
                QMessageBox.warning(self, "Campos Obrigatórios", 
                                f"Por favor preencha os seguintes campos:\n\n• {'\n• '.join(empty_fields)}")
                return
            
            confirmed_items = [item for item in self.analysis_items if item['status'] == 'Confirmado']
            if not confirmed_items:
                QMessageBox.warning(self, "Aviso", "Não há itens confirmados para gerar o relatório.")
                return
                
            timestamp = datetime.now().strftime("%d%m%Y_%H%M%S")
            
            original_paths_for_report = []
            for path, data in self.image_data.items(): # Check original image_data for paths
                 is_valid_for_report_base_dir = True
                 # This logic to find the item might be redundant if self.image_paths is reliable
                 list_item_text_found = ""
                 for i in range(self.list_widget.count()): # This list_widget is now for analysis_items
                     # We need a more robust way to link back or use a stored original path list
                     pass # For now, assume self.image_paths is correctly populated from load.
                 
                 # Simplified: use self.image_paths if available and populated.
                 # This assumes self.image_paths contains paths that led to the current analysis_items.
                 if self.image_paths: # If self.image_paths was populated
                     original_paths_for_report = self.image_paths
                     break # Found a source for paths

            if not original_paths_for_report:
                 # Fallback if self.image_paths is empty, try to get from analysis_items (less ideal)
                 if self.analysis_items:
                     first_recorte_path = self.analysis_items[0]['recorte']
                     # Try to infer base_dir from recorte path (e.g., ../ from 'imagens_recortadas')
                     base_dir_inferred = os.path.dirname(os.path.dirname(first_recorte_path))
                     if os.path.isdir(base_dir_inferred):
                         base_dir = base_dir_inferred
                     else: # Last resort: use default_directory
                         base_dir = self.default_directory
                         QMessageBox.warning(self, "Aviso de Diretório", f"Não foi possível determinar o diretório original das imagens. O relatório será salvo em: {base_dir}")
                 else: # No analysis_items either
                    QMessageBox.critical(self, "Erro", "Não foi possível determinar o diretório para salvar o relatório.")
                    return
            else:
                base_dir = os.path.dirname(original_paths_for_report[0])

            filename = os.path.join(base_dir, f"relatorio_{required_inputs['Análise']}_{timestamp}.csv")
            
            with open(filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["Informações da Análise"])
                writer.writerow(["Análise", required_inputs['Análise']])
                writer.writerow(["Espécie", required_inputs['Espécie']])
                writer.writerow(["Temperatura", f"{required_inputs['Temperatura']} °C"])
                writer.writerow(["Tempo", f"{required_inputs['Tempo']} h"])
                writer.writerow([]) 
                writer.writerow(["Imagem", "Total Sementes", "Sementes Viáveis", "Sementes Inviáveis", "% Viabilidade"])
                
                total_seeds, total_viable = 0, 0
                for item in confirmed_items:
                    name = os.path.basename(item['recorte'])
                    counts = item['counts']
                    viability = round((counts['viable'] / counts['total']) * 100, 2) if counts['total'] > 0 else 0
                    writer.writerow([name, counts['total'], counts['viable'], counts['inviable'], f"{viability}%"])
                    total_seeds += counts['total']; total_viable += counts['viable']
                    
                writer.writerow([])
                overall_viability = round((total_viable / total_seeds) * 100, 2) if total_seeds > 0 else 0
                writer.writerow(["TOTAL", total_seeds, total_viable, total_seeds - total_viable, f"{overall_viability}%"])
            
            QMessageBox.information(self, "Relatório Gerado", f"Relatório CSV criado com sucesso:\n{filename}")
        except Exception as e:
            print(f"Erro ao gerar relatório: {e}"); traceback.print_exc()
            QMessageBox.critical(self, "Erro", f"Erro ao gerar arquivo CSV:\n{str(e)}\nVerifique o console para detalhes.")

    def show_help(self):
        help_text = """
        <h3>Ajuda - Analisador de Sementes de Orquídea</h3>
        <p><b>Como utilizar o programa:</b></p>
        <ol>
        <li><b>Carregamento de imagens:</b> Clique em "Selecionar Arquivos" ou "Selecionar Pasta". Imagens muito pequenas ou corrompidas serão marcadas.</li>
        <li><b>Delimitar imagem:</b> Posicione o retângulo vermelho sobre a área desejada e clique em "Delimitar [D]" (ou use Enter/Ctrl+D). Repita para todas as imagens válidas.</li>
        <li><b>Analisar imagens:</b> Após delimitar todas as imagens válidas, clique em "Analisar Imagens". As imagens serão recortadas em seções.</li>
        <li><b>Confirmar/Remover análises:</b> Selecione uma seção e clique em "Confirmar [C]" ou "Remover [R]" (ou use Ctrl+C/Ctrl+R) para marcar/alterar seu status.
        Use "Confirmar Todas", "Remover Todas", "Confirmar Restantes" ou "Remover Restantes" para ações em lote.</li>
        <li><b>Gerar relatório:</b> Após processar todas as seções, preencha os campos obrigatórios (Análise, Espécie, etc.) e clique em "Confirmar e Gerar Relatório".</li>
        </ol>
        <p><b>Campos obrigatórios para o relatório:</b> Análise, Espécie, Temp. Armazenamento (°C), Tempo (h).</p>
        <p><b>Atalhos de teclado:</b> Enter/Ctrl+D (Delimitar), Ctrl+C (Confirmar), Ctrl+R (Remover).</p>
        """
        msg = QMessageBox(self); msg.setWindowTitle("Ajuda")
        msg.setTextFormat(Qt.TextFormat.RichText); msg.setText(help_text)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok); msg.exec()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = SeedAnalyzerApp()
    win.showMaximized()
    sys.exit(app.exec())