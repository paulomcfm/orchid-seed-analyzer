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
        """Display a previously defined region of interest."""
        if not self.pixmap_item:
            return
            
        # Get the ROI coordinates from original image
        orig_x, orig_y, orig_w, orig_h = roi
        
        # Scale to the current display size
        scaled_x = orig_x * self.current_scale_factor
        scaled_y = orig_y * self.current_scale_factor
        
        # Create or reposition the rectangle
        if not self.rect_item:
            self.create_initial_rectangle(self.pixmap_item.boundingRect())
            
        # Position the rectangle
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

        # Top inputs with explicit variable names
        fields = QWidget()
        fields.setFixedHeight(24) 
        f_layout = QHBoxLayout(fields)
        f_layout.setContentsMargins(2, 0, 2, 0)
        f_layout.setSpacing(3)

        # Create input fields with explicit names
        self.input_analise = QLineEdit()
        self.input_especie = QLineEdit()  
        self.input_temp = QLineEdit()
        self.input_tempo = QLineEdit()

        self.input_analise.setPlaceholderText("Digite o nome da análise")
        self.input_especie.setPlaceholderText("Digite o nome da espécie")
        self.input_temp.setPlaceholderText("Digite a temperatura em °C")
        self.input_tempo.setPlaceholderText("Digite o tempo em horas")

        for field in [self.input_analise, self.input_especie, self.input_temp, self.input_tempo]:
            field.setMaximumHeight(20)  # Reduced from 22px to 20px
            field.setFixedHeight(20)  

        self.input_temp.setValidator(QDoubleValidator())  # Allows decimals for temperature
        self.input_tempo.setValidator(QIntValidator())    # Only whole numbers for hours

        # Add labels and fields to layout
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

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel (narrow)
        left = QWidget(); left.setMinimumWidth(60)
        l_layout = QVBoxLayout(left)
        self.btn_load_files = QPushButton("Selecionar Arquivos")
        self.btn_load_folder = QPushButton("Selecionar Pasta")
        self.list_widget = QListWidget()
        for w in (self.btn_load_files, self.btn_load_folder, QLabel("Itens:"), self.list_widget):
            l_layout.addWidget(w)
        splitter.addWidget(left)

        # Center panel (wide)
        center = QWidget()
        c_layout = QVBoxLayout(center)
        self.image_view = PlacementView()
        c_layout.addWidget(self.image_view, 3)
        # Recortes e análise lado a lado
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

        # Right panel (narrow)
        right = QWidget(); right.setMinimumWidth(60)
        r_layout = QVBoxLayout(right)
        self.details_text = QTextEdit(); self.details_text.setReadOnly(True)
        buttons = {name: QPushButton(text) for name, text in [
            ('btn_delimit', 'Delimitar [D]'),
            ('btn_analyze', 'Analisar Imagens'),
            ('btn_confirm', 'Confirmar [C]'),
            ('btn_remove', 'Remover [R]'),
            ('btn_confirm_all', 'Confirmar Todas'),
            ('btn_remove_all', 'Remover Todas'),
            ('btn_confirm_report', 'Confirmar e Gerar Relatório')
        ]}
        for key, btn in buttons.items():
            setattr(self, key, btn)
            r_layout.addWidget(btn)
        self.btn_delimit.setEnabled(False)
        self.btn_analyze.setEnabled(False)
        for name in ('btn_confirm', 'btn_remove', 'btn_confirm_all', 'btn_remove_all', 'btn_confirm_report'):
            getattr(self, name).setVisible(False)
        r_layout.insertWidget(0, self.details_text)
        r_layout.addStretch()
        splitter.addWidget(right)

        # Proportions
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 16)
        splitter.setStretchFactor(2, 1)

        v_main.addWidget(splitter)

        # Connections
        self.btn_load_files.clicked.connect(self.load_files)
        self.btn_load_folder.clicked.connect(self.load_folder)
        self.list_widget.currentItemChanged.connect(self.display_selected_item)
        self.btn_delimit.clicked.connect(self.confirm_delimit)
        self.btn_analyze.clicked.connect(self.analyze_images)
        self.btn_confirm.clicked.connect(self.confirm_current_analysis)
        self.btn_remove.clicked.connect(self.remove_current_analysis)
        self.btn_confirm_all.clicked.connect(self.confirm_all)
        self.btn_remove_all.clicked.connect(self.remove_all)
        self.btn_confirm_report.clicked.connect(self.generate_report)

        self.statusBar().showMessage("Pronto.")

    def keyPressEvent(self, event):
        # Check if Enter/Return is pressed and we're in delimitation mode
        if (event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter) and \
        not self.analysis_stage and \
        self.btn_delimit.isVisible() and \
        self.btn_delimit.isEnabled():
            # Call the same function as the "Confirmar Delimitação" button
            self.confirm_delimit()
        # Add Ctrl+D as an additional shortcut for delimitation
        elif event.key() == Qt.Key.Key_D and \
            event.modifiers() & Qt.KeyboardModifier.ControlModifier and \
            not self.analysis_stage and \
            self.btn_delimit.isVisible() and \
            self.btn_delimit.isEnabled():
            self.confirm_delimit()
        # Handle Ctrl+C to confirm in analysis mode
        elif event.key() == Qt.Key.Key_C and \
            event.modifiers() & Qt.KeyboardModifier.ControlModifier and \
            self.analysis_stage and \
            self.btn_confirm.isVisible():
            self.confirm_current_analysis()
        # Handle Ctrl+R to remove in analysis mode
        elif event.key() == Qt.Key.Key_R and \
            event.modifiers() & Qt.KeyboardModifier.ControlModifier and \
            self.analysis_stage and \
            self.btn_remove.isVisible():
            self.remove_current_analysis()
        else:
            # Pass other key events to parent class
            super().keyPressEvent(event)

    def update_details_text(self):
        if not getattr(self, 'current_image', None): return
        data = self.image_data.get(self.current_image, {})
        basename = os.path.basename(self.current_image)
        roi = data.get('roi')
        txt = f"Arquivo: {basename}\nROI: x={roi[0]:.1f}, y={roi[1]:.1f}, w={roi[2]}, h={roi[3]}" if roi else f"Arquivo: {basename}\nROI não definida"
        self.details_text.setText(txt)

    def load_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Selecionar Arquivos de Imagem", self.default_directory,
                                                "Imagens (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if files:
            self.default_directory = os.path.dirname(files[0])
            self.process_selected_paths(files)

    def load_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecionar Pasta com Imagens", self.default_directory)
        if folder:
            imgs = [os.path.join(folder, fn) for fn in sorted(os.listdir(folder))
                    if fn.lower().endswith(('.png','.jpg','.jpeg','.bmp','.tif','.tiff'))]
            self.process_selected_paths(imgs)

    def process_selected_paths(self, paths):
        self.analysis_stage = False

        # Clear all input fields when loading new images
        self.input_analise.clear()
        self.input_especie.clear()
        self.input_temp.clear()
        self.input_tempo.clear()

        self.image_paths = paths
        self.image_data.clear()
        self.analysis_items.clear()
        self.list_widget.clear()
        self.details_text.clear()
        self.current_image = None
        self.image_view.setVisible(True)
        self.recorte_container.setVisible(False)
        self.btn_delimit.setVisible(True)
        self.btn_analyze.setVisible(False)
        for w in [self.btn_confirm, self.btn_remove, self.btn_confirm_all, self.btn_remove_all, self.btn_confirm_report]:
            w.setVisible(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        # Show initial loading message
        self.statusBar().showMessage(f"Carregando 0 de {len(paths)} imagens...")
        QApplication.processEvents()  # Process events to update UI
        
        valid_images = 0
        for i, path in enumerate(paths):
            # Update status bar with progress
            self.statusBar().showMessage(f"Carregando {i+1} de {len(paths)} imagens...")
            QApplication.processEvents()  # Process events to update UI
            
            try:
                # Open the image and check dimensions
                pil = Image.open(path).convert('RGB')
                width, height = pil.size
                
                # Check if image is large enough for the delimitation rectangle
                if width < TARGET_RECT_WIDTH_ORIGINAL or height < TARGET_RECT_HEIGHT_ORIGINAL:
                    # Image too small, add error entry
                    itm = QListWidgetItem(f"{os.path.basename(path)} [TAMANHO INSUFICIENTE]")
                    itm.setForeground(QColor('red'))
                    self.list_widget.addItem(itm)
                    continue
                    
                # Image passed validation
                self.image_data[path] = {'pil': pil, 'roi': None}
                self.list_widget.addItem(QListWidgetItem(os.path.basename(path)))
                valid_images += 1
                
            except Exception as e:
                itm = QListWidgetItem(f"{os.path.basename(path)} [ERRO]")
                itm.setForeground(QColor('red'))
                self.list_widget.addItem(itm)

        self.statusBar().showMessage(f"Pronto.")
        QApplication.processEvents() 
        
        QApplication.restoreOverrideCursor()
        
        # Show message if no valid images were loaded
        if valid_images == 0:
            QMessageBox.warning(self, "Aviso", 
                            "Nenhuma imagem válida foi carregada. Todas as imagens são menores que o tamanho mínimo necessário " +
                            f"({TARGET_RECT_WIDTH_ORIGINAL}x{TARGET_RECT_HEIGHT_ORIGINAL} pixels).")
        else:
            # Select first valid image
            for i in range(self.list_widget.count()):
                item_text = self.list_widget.item(i).text()
                if '[ERRO]' not in item_text and '[TAMANHO INSUFICIENTE]' not in item_text:
                    self.list_widget.setCurrentRow(i)
                    break

    def display_selected_item(self, current, previous=None):
        if not current: return
        name = current.text()
        if not self.analysis_stage:
            if '[ERRO]' in name:
                self.image_view._scene.clear()
                self.details_text.setText("Erro ao carregar esta imagem.")
                self.btn_delimit.setEnabled(False)
                return
            path = next((p for p in self.image_data if os.path.basename(p)==name.replace(' [D]','')), None)
            if not path: return
            self.current_image = path
            data = self.image_data[path]
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            arr = np.array(data['pil'], dtype=np.uint8)
            h, w, _ = arr.shape
            img = QImage(arr.data, w, h, w*3, QImage.Format.Format_RGB888)
            pix = QPixmap.fromImage(img)
            self.image_view.set_image(pix)

            roi_data = data.get('roi')
            if roi_data:
                self.image_view.show_existing_roi(roi_data)
           
            self.btn_delimit.setEnabled(True)
            self.update_details_text()
            QApplication.restoreOverrideCursor()
        else:
            idx = self.list_widget.currentRow()
            item = self.analysis_items[idx]
            self.scene_orig.clear(); self.scene_orig.addPixmap(QPixmap(item['recorte']))
            self.view_orig.fitInView(self.scene_orig.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.scene_analyzed.clear(); self.scene_analyzed.addPixmap(QPixmap(item['analysed']))
            self.view_analyzed.fitInView(self.scene_analyzed.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            cnt = item['counts']
            status = item['status'] or 'Aguardando'
            self.details_text.setText(
                f"Arquivo: {os.path.basename(item['recorte'])}\n"
                f"Total sementes: {cnt['total']}\nViáveis: {cnt['viable']}\nInviáveis: {cnt['inviable']}\nStatus: {status}"
            )

    def confirm_delimit(self):
        if not self.current_image: return
        roi = self.image_view.get_roi_original_coords()
        if not roi:
            QMessageBox.warning(self, "Aviso", "Não foi possível obter coordenadas.")
            return
        self.image_data[self.current_image]['roi'] = roi
        itm = self.list_widget.currentItem()
        if itm and not itm.text().endswith(' [D]'):
            itm.setText(itm.text() + ' [D]')
        if all(d['roi'] is not None for d in self.image_data.values()):
            self.btn_analyze.setVisible(True)
            self.btn_analyze.setEnabled(True)
            QMessageBox.information(self, "Info", "Todas as imagens foram delimitadas.")
        for i in range(self.list_widget.count()):
            txt = self.list_widget.item(i).text()
            if '[ERRO]' not in txt and not txt.endswith(' [D]'):
                self.list_widget.setCurrentRow(i)
                break

    def update_report_button_state(self):
        """Enable report button only when all items have been processed."""
        all_processed = all(item['status'] in ['Confirmado', 'Removido'] for item in self.analysis_items)
        self.btn_confirm_report.setEnabled(all_processed)

    # --- Analyze images: crop, stub analysis, switch UI ---
    def analyze_images(self):
        # ensure all delim
        if any(data['roi'] is None for data in self.image_data.values()):
            QMessageBox.warning(self, "Aviso", "Delimite todas as imagens antes de analisar.")
            return

        # Initial status update
        self.statusBar().showMessage("Preparando análise...")
        QApplication.processEvents()

        # prepare output folder
        base = os.path.dirname(self.image_paths[0])
        out_dir = os.path.join(base, 'imagens_recortadas')
        os.makedirs(out_dir, exist_ok=True)
        self.analysis_items = []
        # cropping and stub analysis
        for path, data in self.image_data.items():
            # Update status with file name
            base_file = os.path.basename(path)
            self.statusBar().showMessage(f"Recortando imagem: {base_file}...")
            QApplication.processEvents()

            ox, oy, ow, oh = map(int, data['roi'])
            tile_w = ow // TILE_COLS
            tile_h = oh // TILE_ROWS
            for idx in range(TILE_COLS * TILE_ROWS):
                row = idx // TILE_COLS
                col = idx % TILE_COLS
                left = ox + col * tile_w
                top = oy + row * tile_h

                # Status update for this specific tile
                self.statusBar().showMessage(f"Recortando imagem {base_file}: seção {idx+1}/{TILE_COLS*TILE_ROWS}...")
                QApplication.processEvents()

                crop = data['pil'].crop((left, top, left+tile_w, top+tile_h))
                base_name = os.path.splitext(os.path.basename(path))[0]
                rec_name = f"{base_name}_{idx+1}.png"
                rec_path = os.path.join(out_dir, rec_name)
                crop.save(rec_path)

                # Status update for analysis
                self.statusBar().showMessage(f"Analisando imagem {base_file}: seção {idx+1}/{TILE_COLS*TILE_ROWS}...")
                QApplication.processEvents()

                # stub analysis: copy for now
                ana_name = f"{base_name}_{idx+1}_analisada.png"
                ana_path = os.path.join(out_dir, ana_name)
                crop.save(ana_path)
                # generic counts
                total = random.randint(5, 15)
                viable = random.randint(0, total)
                invi = total - viable
                self.analysis_items.append({
                    'recorte': rec_path,
                    'analysed': ana_path,
                    'counts': {'total': total, 'viable': viable, 'inviable': invi},
                    'status': None
                })

        # Final status update
        self.statusBar().showMessage("Pronto.")
        QApplication.processEvents()

        # switch to analysis stage
        self.analysis_stage = True
        self.image_view.setVisible(False)
        self.recorte_container.setVisible(True)
        self.btn_delimit.setVisible(False)
        self.btn_analyze.setVisible(False)
        for w in [self.btn_confirm_all, self.btn_remove_all, self.btn_confirm, self.btn_remove, self.btn_confirm_report]:
            w.setVisible(True)

        self.btn_confirm_report.setEnabled(False)
        # repopulate list
        self.list_widget.clear()
        for item in self.analysis_items:
            self.list_widget.addItem(os.path.basename(item['recorte']))
        # connect to analysis display
        self.list_widget.currentItemChanged.disconnect()
        self.list_widget.currentItemChanged.connect(self.display_selected_item)
        # select first
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        
        self.activateWindow()  # Make sure the window stays active
        self.list_widget.setFocus()  

    # --- Display selected analysis item ---
    def display_selected_analysis_item(self, current, previous=None):
        if not current:
            return
        name = current.text()
        idx = self.list_widget.currentRow()
        data = self.analysis_items[idx]
        # show original recorte
        pix_o = QPixmap(data['recorte'])
        self.scene_orig.clear(); self.scene_orig.addPixmap(pix_o)
        # show analysed
        pix_a = QPixmap(data['analysed'])
        self.scene_analyzed.clear(); self.scene_analyzed.addPixmap(pix_a)
        # details
        cnt = data['counts']
        status = data['status'] or 'Aguardando'
        txt = f"Arquivo: {name}\nTotal sementes: {cnt['total']}\nViáveis: {cnt['viable']}\nInviáveis: {cnt['inviable']}\nStatus: {status}"
        self.details_text.setText(txt)

    # --- Confirm/Remove logic ---
    # Modified confirm_current_analysis method
    def confirm_current_analysis(self):
        idx = self.list_widget.currentRow()
        self.analysis_items[idx]['status'] = 'Confirmado'
        itm = self.list_widget.item(idx)
        
        # Get base filename without any status tags
        base_name = os.path.basename(self.analysis_items[idx]['recorte'])
        itm.setText(f"{base_name} [C]")
        self.update_report_button_state()
        self.next_analysis()

    # Modified remove_current_analysis method
    def remove_current_analysis(self):
        idx = self.list_widget.currentRow()
        self.analysis_items[idx]['status'] = 'Removido'
        itm = self.list_widget.item(idx)
        
        # Get base filename without any status tags
        base_name = os.path.basename(self.analysis_items[idx]['recorte'])
        itm.setText(f"{base_name} [R]")
        self.update_report_button_state()
        self.next_analysis()

    def next_analysis(self):
        # advance to next unmarked
        for i, it in enumerate(self.analysis_items):
            if it['status'] is None:
                self.list_widget.setCurrentRow(i)
                return
        QMessageBox.information(self, "Info", "Todos os itens foram marcados.")

    def confirm_all(self):
        for i, it in enumerate(self.analysis_items):
            it['status'] = 'Confirmado'
            self.list_widget.item(i).setText(f"{os.path.basename(it['recorte'])} [C]")
        self.update_report_button_state()
        # Use display_selected_item (not display_selected_analysis_item)
        current_item = self.list_widget.currentItem()
        if current_item:
            self.display_selected_item(current_item)

    def remove_all(self):
        for i, it in enumerate(self.analysis_items):
            it['status'] = 'Removido'
            self.list_widget.item(i).setText(f"{os.path.basename(it['recorte'])} [R]")
        self.update_report_button_state()
        # Use display_selected_item (not display_selected_analysis_item)
        current_item = self.list_widget.currentItem()
        if current_item:
            self.display_selected_item(current_item)

    # --- Generate report ---
    def generate_report(self):
        # Get text values with proper error handling
        try:
            required_inputs = {
                "Análise": self.input_analise.text().strip(),
                "Espécie": self.input_especie.text().strip(),
                "Temperatura": self.input_temp.text().strip(),
                "Tempo": self.input_tempo.text().strip()
            }
            
            # Find any empty fields
            empty_fields = [field for field, value in required_inputs.items() if not value]
            
            # If any fields are empty, show warning
            if empty_fields:
                empty_list = "\n• ".join(empty_fields)
                QMessageBox.warning(self, "Campos Obrigatórios", 
                                f"Por favor preencha os seguintes campos:\n\n• {empty_list}")
                return
            
            # Continue with report generation
            print("===== Relatório =====")
            print(f"Análise: {required_inputs['Análise']}")
            print(f"Espécie: {required_inputs['Espécie']}")
            print(f"Temperatura: {required_inputs['Temperatura']} °C")
            print(f"Tempo: {required_inputs['Tempo']} h")
            for it in self.analysis_items:
                if it['status'] == 'Confirmado':
                    name = os.path.basename(it['recorte'])
                    cnt = it['counts']
                    print(f"{name}: Total={cnt['total']}, Viáveis={cnt['viable']}, Inviáveis={cnt['inviable']}")
            QMessageBox.information(self, "Relatório", "Relatório impresso no console.")
        except Exception as e:
            print(f"Erro ao gerar relatório: {e}")
            traceback.print_exc()
            QMessageBox.critical(self, "Erro", "Erro ao acessar campos de entrada. Verifique o console para detalhes.")

# --- Main ---
if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = SeedAnalyzerApp()
    win.showMaximized()
    sys.exit(app.exec())
