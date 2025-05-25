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
from PyQt6.QtGui import (QPixmap, QImage, QPainter, QPen, QColor, QDoubleValidator, QIntValidator,
                         QWheelEvent, QKeyEvent) 
from PyQt6.QtCore import Qt, QRectF, QPointF, QSize, QSizeF
from PIL import Image
import traceback
import csv
from datetime import datetime
from ultralytics import YOLO
import cv2

# --- Configuration ---
TARGET_RECT_WIDTH_ORIGINAL = 5676
TARGET_RECT_HEIGHT_ORIGINAL = 1892
TILE_COLS = 6
TILE_ROWS = 2
EXPECTED_PROCESSED_WIDTH = 946
EXPECTED_PROCESSED_HEIGHT = 946
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

class NavigableGraphicsView(QGraphicsView):
    def __init__(self, list_widget_ref, parent=None):
        super().__init__(parent)
        self.list_widget_ref = list_widget_ref
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus) 

    def wheelEvent(self, event: QWheelEvent):
        if not self.list_widget_ref or self.list_widget_ref.count() == 0:
            super().wheelEvent(event)
            return

        num_degrees = event.angleDelta().y() / 8
        num_steps = num_degrees / 15 

        current_row = self.list_widget_ref.currentRow()
        new_row = current_row

        if num_steps > 0: 
            new_row = max(0, current_row - 1)
        elif num_steps < 0: 
            new_row = min(self.list_widget_ref.count() - 1, current_row + 1)

        if new_row != current_row:
            self.list_widget_ref.setCurrentRow(new_row)
            event.accept() 
        else:
            event.accept()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        processed_by_us = False

        if self.list_widget_ref and self.list_widget_ref.count() > 0:
            current_row = self.list_widget_ref.currentRow()
            new_row = current_row

            if key == Qt.Key.Key_Up:
                new_row = max(0, current_row - 1)
                if new_row != current_row:
                    self.list_widget_ref.setCurrentRow(new_row)
                event.accept()
                processed_by_us = True
            elif key == Qt.Key.Key_Down:
                new_row = min(self.list_widget_ref.count() - 1, current_row + 1)
                if new_row != current_row:
                    self.list_widget_ref.setCurrentRow(new_row)
                event.accept()
                processed_by_us = True
        
        if not processed_by_us:
            super().keyPressEvent(event)

class PlacementView(QGraphicsView):
    def __init__(self, list_widget_ref, parent=None): 
        super().__init__(parent)
        self.list_widget_ref = list_widget_ref 
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.pixmap_item = None
        self.rect_item = None
        self.current_scale_factor = 1.0
        self.original_image_size = QSize()
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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

    def wheelEvent(self, event: QWheelEvent):
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event) 
            return

        if not self.list_widget_ref or self.list_widget_ref.count() == 0:
            super().wheelEvent(event)
            return

        num_degrees = event.angleDelta().y() / 8
        num_steps = num_degrees / 15

        current_row = self.list_widget_ref.currentRow()
        new_row = current_row

        if num_steps > 0: 
            new_row = max(0, current_row - 1)
        elif num_steps < 0: 
            new_row = min(self.list_widget_ref.count() - 1, current_row + 1)

        if new_row != current_row:
            self.list_widget_ref.setCurrentRow(new_row)
            event.accept()
        else:
            event.accept()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        processed_by_us = False

        if self.list_widget_ref and self.list_widget_ref.count() > 0:
            current_row = self.list_widget_ref.currentRow()
            new_row = current_row

            if key == Qt.Key.Key_Up:
                new_row = max(0, current_row - 1)
                if new_row != current_row:
                    self.list_widget_ref.setCurrentRow(new_row)
                event.accept()
                processed_by_us = True
            elif key == Qt.Key.Key_Down:
                new_row = min(self.list_widget_ref.count() - 1, current_row + 1)
                if new_row != current_row:
                    self.list_widget_ref.setCurrentRow(new_row)
                event.accept()
                processed_by_us = True
        
        if not processed_by_us:
            super().keyPressEvent(event)


class SeedAnalyzerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Delimitador de Sementes")
        self.resize(1200, 700)
        self.image_paths = []
        self.image_data = {}
        self.analysis_items = []
        self.analysis_stage = False
        self.processed_files_base_dir = None
        docs = "C:\\Documentos"
        self.default_directory = docs if os.path.isdir(docs) else os.path.expanduser("~")
        self.yolo_model = None
        self.model_path = "model_weights/best.pt" 
        try:
            if os.path.exists(self.model_path):
                self.yolo_model = YOLO(self.model_path)
            else:
                print(f"ERRO: Arquivo do modelo YOLO não encontrado em: {self.model_path}")
        except Exception as e:
            print(f"Erro ao carregar o modelo YOLO: {e}")
            QMessageBox.critical(self, "Erro de Modelo", f"Não foi possível carregar o modelo YOLO de '{self.model_path}'. Verifique o caminho e a instalação do Ultralytics.\n\nErro: {e}")
            self.yolo_model = None

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
        self.btn_load_processed_files = QPushButton("Selecionar Arquivos Processados")
        self.btn_load_processed_folder = QPushButton("Selecionar Pasta Processada") 
        self.list_widget = QListWidget() 
        for w in (self.btn_load_files, self.btn_load_folder, QLabel("Itens:"), self.list_widget):
            l_layout.addWidget(w)
        l_layout.addWidget(self.btn_load_processed_files)
        l_layout.addWidget(self.btn_load_processed_folder)
        splitter.addWidget(left)

        center = QWidget()
        c_layout = QVBoxLayout(center)
        self.image_view = PlacementView(self.list_widget) 
        c_layout.addWidget(self.image_view, 3)
        self.recorte_container = QWidget()
        rc_layout = QHBoxLayout(self.recorte_container)
        
        self.view_orig = NavigableGraphicsView(self.list_widget) 
        self.scene_orig = QGraphicsScene(self.view_orig)
        self.view_orig.setScene(self.scene_orig)
        rc_layout.addWidget(self.view_orig, 1)
        
        self.view_analyzed = NavigableGraphicsView(self.list_widget) 
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
        self.btn_load_processed_files.clicked.connect(self.load_processed_files) 
        self.btn_load_processed_folder.clicked.connect(self.load_processed_folder)
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

    def keyPressEvent(self, event: QKeyEvent): 
        if (event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter) and \
           not self.analysis_stage and self.btn_delimit.isVisible() and self.btn_delimit.isEnabled():
            self.confirm_delimit()
            event.accept()
        elif event.key() == Qt.Key.Key_D and event.modifiers() & Qt.KeyboardModifier.ControlModifier and \
             not self.analysis_stage and self.btn_delimit.isVisible() and self.btn_delimit.isEnabled():
            self.confirm_delimit()
            event.accept()
        elif event.key() == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier and \
             self.analysis_stage and self.btn_confirm.isVisible() and self.btn_confirm.isEnabled():
            self.confirm_current_analysis()
            event.accept()
        elif event.key() == Qt.Key.Key_R and event.modifiers() & Qt.KeyboardModifier.ControlModifier and \
             self.analysis_stage and self.btn_remove.isVisible() and self.btn_remove.isEnabled():
            self.remove_current_analysis()
            event.accept()
        else:
            super().keyPressEvent(event)

    def update_details_text(self):
        if not self.analysis_stage:
            if not getattr(self, 'current_image', None) or not self.list_widget.currentItem(): 
                self.details_text.setText("Nenhum arquivo selecionado ou lista vazia.")
                return
            data = self.image_data.get(self.current_image, {})
            basename = os.path.basename(self.current_image)
            roi = data.get('roi')
            txt = f"Arquivo: {basename}\nROI: x={roi[0]:.1f}, y={roi[1]:.1f}, w={roi[2]}, h={roi[3]}" if roi else f"Arquivo: {basename}\nROI não definida"
            self.details_text.setText(txt)
        else: 
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

    def load_processed_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Selecionar Arquivos Processados", self.default_directory,
                                                "Imagens (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if files:
            self.default_directory = os.path.dirname(files[0])
            self.process_selected_processed_paths(files)

    def load_processed_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecionar Pasta com Imagens Processadas", self.default_directory)
        if folder:
            self.default_directory = folder
            imgs = [os.path.join(folder, fn) for fn in sorted(os.listdir(folder))
                    if fn.lower().endswith(('.png','.jpg','.jpeg','.bmp','.tif','.tiff'))]
            self.process_selected_processed_paths(imgs)

    def process_selected_processed_paths(self, paths):
        self.analysis_stage = False 
        self.input_analise.clear(); self.input_especie.clear(); self.input_temp.clear(); self.input_tempo.clear()
        self.image_paths = [] 
        self.image_data.clear() 
        self.analysis_items.clear()
        self.list_widget.clear()
        self.details_text.clear()
        self.current_image = None 
        self.processed_files_base_dir = None 

        if not paths:
            self.statusBar().showMessage("Nenhum arquivo processado selecionado.")
            self.update_analysis_action_buttons_state()
            return

        if not self.yolo_model:
             QMessageBox.critical(self, "Erro de Modelo", "O modelo YOLO não está carregado. A análise não pode prosseguir.")
             self.statusBar().showMessage("Falha ao carregar: Modelo YOLO não disponível.")
             self.image_view.setVisible(True) 
             self.recorte_container.setVisible(False)
             self.btn_delimit.setVisible(True) 
             self.btn_delimit.setEnabled(False)
             self.btn_analyze.setVisible(False)
             for btn_name in ['btn_confirm_all', 'btn_remove_all', 'btn_confirm_remaining', 
                               'btn_remove_remaining', 'btn_confirm', 'btn_remove', 'btn_confirm_report']:
                 if hasattr(self, btn_name): getattr(self, btn_name).setVisible(False)
             self.update_analysis_action_buttons_state()
             return

        self.processed_files_base_dir = os.path.dirname(paths[0]) 

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage(f"Validando 0 de {len(paths)} imagens processadas...")
        QApplication.processEvents()

        validated_paths_for_yolo = []
        for i, rec_path_validate in enumerate(paths):
            self.statusBar().showMessage(f"Validando {i+1} de {len(paths)} imagens...")
            QApplication.processEvents()
            try:
                with Image.open(rec_path_validate) as img_validate:
                    width, height = img_validate.size
                if width != EXPECTED_PROCESSED_WIDTH or height != EXPECTED_PROCESSED_HEIGHT:
                    error_msg = f"{os.path.basename(rec_path_validate)} [DIMENSÕES INVÁLIDAS: {width}x{height}, esperado {EXPECTED_PROCESSED_WIDTH}x{EXPECTED_PROCESSED_HEIGHT}]"
                    itm = QListWidgetItem(error_msg)
                    itm.setForeground(QColor('red'))
                    self.list_widget.addItem(itm) 
                    print(error_msg)
                else:
                    validated_paths_for_yolo.append(rec_path_validate) 
            except Exception as e:
                error_msg = f"{os.path.basename(rec_path_validate)} [ERRO AO ABRIR/VALIDAR]"
                itm = QListWidgetItem(error_msg)
                itm.setForeground(QColor('red'))
                self.list_widget.addItem(itm)
                print(f"Erro ao validar {rec_path_validate}: {e}")
                traceback.print_exc()
        
        if not validated_paths_for_yolo:
            QApplication.restoreOverrideCursor()
            self.statusBar().showMessage("Nenhuma imagem processada válida encontrada após validação de dimensões.")
            if self.list_widget.count() > 0:
                self.list_widget.setCurrentRow(0) 
            else: 
                self.update_details_text()
            
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
            self.update_analysis_action_buttons_state() 
            return

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

        yolo_analyzed_output_dir = os.path.join(self.processed_files_base_dir, 'imagens_processadas_analisadas')
        os.makedirs(yolo_analyzed_output_dir, exist_ok=True)
        
        self.statusBar().showMessage(f"Iniciando análise YOLO em 0 de {len(validated_paths_for_yolo)} imagens...")
        QApplication.processEvents()
        
        self.list_widget.clear() 
        self.analysis_items = [] 

        processed_yolo_count = 0
        for i, rec_path in enumerate(validated_paths_for_yolo): 
            self.statusBar().showMessage(f"Analisando com YOLO {i+1} de {len(validated_paths_for_yolo)} imagens...")
            QApplication.processEvents()
            try:
                analyzed_yolo_img_path, counts = self.perform_yolo_analysis(rec_path, yolo_analyzed_output_dir)
                
                self.analysis_items.append({
                    'recorte': rec_path,                 
                    'analysed': analyzed_yolo_img_path,  
                    'counts': counts,
                    'status': None 
                })
                self.list_widget.addItem(QListWidgetItem(os.path.basename(rec_path))) 
                processed_yolo_count += 1
            except Exception as e: 
                error_msg_yolo = f"{os.path.basename(rec_path)} [ERRO NA ANÁLISE YOLO]"
                itm = QListWidgetItem(error_msg_yolo)
                itm.setForeground(QColor('magenta')) 
                self.list_widget.addItem(itm)
                self.analysis_items.append({
                    'recorte': rec_path, 
                    'analysed': rec_path,
                    'counts': {'total': 0, 'viable': 0, 'inviable': 0},
                    'status': 'Erro na Análise YOLO'
                })
                print(f"Erro durante análise YOLO da imagem processada {rec_path}: {e}")
                traceback.print_exc()

        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(f"Análise YOLO concluída. {processed_yolo_count} imagens prontas para revisão.")
        
        self.analysis_stage = True 
        
        try:
            self.list_widget.currentItemChanged.disconnect()
        except TypeError: 
            pass
        self.list_widget.currentItemChanged.connect(self.display_selected_item)
        
        if self.list_widget.count() > 0:
            first_selectable_idx = -1
            for item_idx in range(self.list_widget.count()):
                if item_idx < len(self.analysis_items) and \
                   self.analysis_items[item_idx].get('status') not in ['Erro na Análise YOLO', 'Erro ao Abrir/Validar']:
                    first_selectable_idx = item_idx
                    break
            
            if first_selectable_idx != -1:
                self.list_widget.setCurrentRow(first_selectable_idx)
            elif self.list_widget.count() > 0:
                self.list_widget.setCurrentRow(0)
        else: 
            self.scene_orig.clear(); self.scene_analyzed.clear()
            self.update_details_text()


        self.update_analysis_action_buttons_state()
        self.activateWindow(); self.list_widget.setFocus()

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
        self.image_data.clear(); self.analysis_items.clear(); self.list_widget.clear() 
        self.current_image = None
        self.processed_files_base_dir = None
        self.image_view.setVisible(True); self.recorte_container.setVisible(False)
        
        self.btn_delimit.setVisible(True)
        self.btn_delimit.setEnabled(False) 
        self.btn_analyze.setVisible(False)
        self.btn_analyze.setEnabled(False) 
        
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
                self.image_data[path] = {'pil': pil, 'roi': None, 'pixmap_display': None}
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
        
        if self.list_widget.count() > 0:
            first_valid_idx = -1
            for i in range(self.list_widget.count()):
                item_text = self.list_widget.item(i).text()
                if '[ERRO]' not in item_text and '[TAMANHO INSUFICIENTE]' not in item_text:
                    first_valid_idx = i
                    break
            if first_valid_idx != -1:
                 self.list_widget.setCurrentRow(first_valid_idx)
            else: 
                self.image_view._scene.clear() 
                self.scene_orig.clear()      
                self.scene_analyzed.clear()  
                self.btn_delimit.setEnabled(False)
                self.update_details_text() 
        else: 
            self.image_view._scene.clear()
            self.scene_orig.clear()
            self.scene_analyzed.clear()
            self.btn_delimit.setEnabled(False)
            self.update_details_text()

        self.update_analysis_action_buttons_state() 

    def display_selected_item(self, current, previous=None):
        if not current:
            if self.analysis_stage:
                self.scene_orig.clear(); self.scene_analyzed.clear()
            else:
                self.image_view._scene.clear()
                self.btn_delimit.setEnabled(False)
            self.update_details_text() 
            self.update_analysis_action_buttons_state()
            return

        name = current.text()
        if not self.analysis_stage:
            self.btn_delimit.setEnabled(False) 
            if '[ERRO]' in name or '[TAMANHO INSUFICIENTE]' in name:
                self.image_view._scene.clear()
            else:
                path = next((p for p in self.image_data if os.path.basename(p) == name.replace(' [D]','')), None)
                if not path: 
                    self.image_view._scene.clear() 
                    self.update_details_text()
                    self.update_analysis_action_buttons_state()
                    return

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
                else: 
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
            else: 
                self.scene_orig.clear(); self.scene_analyzed.clear()
        
        self.update_details_text()
        self.update_analysis_action_buttons_state()


    def confirm_delimit(self):
        current_list_item = self.list_widget.currentItem()
        if not self.current_image or not current_list_item:
            if not self.current_image:
                 QMessageBox.warning(self, "Aviso", "Nenhuma imagem principal selecionada para delimitar.")
            return

        current_text = current_list_item.text()
        if '[ERRO]' in current_text or '[TAMANHO INSUFICIENTE]' in current_text:
            QMessageBox.warning(self, "Aviso", "Não é possível delimitar uma imagem com erro ou tamanho insuficiente.")
            return

        roi = self.image_view.get_roi_original_coords()
        if not roi:
            QMessageBox.warning(self, "Aviso", "Não foi possível obter coordenadas.")
            return
            
        self.image_data[self.current_image]['roi'] = roi
        
        base_name = os.path.basename(self.current_image)
        if not current_list_item.text().endswith(' [D]'):
            current_list_item.setText(base_name + ' [D]')
        
        all_valid_delimited_so_far = True 
        has_any_valid_image = False
        next_undelimited_row = -1
        current_row_idx = self.list_widget.currentRow()

        # Check if all valid images are delimited to enable analyze button
        for i in range(self.list_widget.count()):
            list_item = self.list_widget.item(i)
            item_text = list_item.text()
            is_error_or_small = '[ERRO]' in item_text or '[TAMANHO INSUFICIENTE]' in item_text
            
            if not is_error_or_small:
                has_any_valid_image = True
                current_item_base_name = item_text.split(" [")[0]
                
                path_key_found = next((p_key for p_key in self.image_data 
                                       if os.path.basename(p_key) == current_item_base_name), None)
                
                if path_key_found and self.image_data[path_key_found].get('roi') is None:
                    all_valid_delimited_so_far = False 

        if has_any_valid_image and all_valid_delimited_so_far:
            self.btn_analyze.setVisible(True)
            self.btn_analyze.setEnabled(True)
            QMessageBox.information(self, "Info", "Todas as imagens válidas foram delimitadas. Pronto para analisar.")
        else:
            self.btn_analyze.setVisible(False)
            self.btn_analyze.setEnabled(False)

        # Find next undelimited valid image, starting from AFTER current one
        for i in range(current_row_idx + 1, self.list_widget.count()):
            list_item = self.list_widget.item(i)
            item_text = list_item.text()
            is_error_or_small = '[ERRO]' in item_text or '[TAMANHO INSUFICIENTE]' in item_text
            current_item_base_name = item_text.split(" [")[0] 
            path_key_next = next((p_key for p_key in self.image_data 
                                  if os.path.basename(p_key) == current_item_base_name), None)

            if not is_error_or_small and path_key_next and self.image_data[path_key_next].get('roi') is None:
                next_undelimited_row = i
                break
        
        # If not found after current, search from beginning UP TO current one
        if next_undelimited_row == -1:
            for i in range(current_row_idx): 
                list_item = self.list_widget.item(i)
                item_text = list_item.text()
                is_error_or_small = '[ERRO]' in item_text or '[TAMANHO INSUFICIENTE]' in item_text
                current_item_base_name = item_text.split(" [")[0]
                path_key_next = next((p_key for p_key in self.image_data 
                                      if os.path.basename(p_key) == current_item_base_name), None)
                if not is_error_or_small and path_key_next and self.image_data[path_key_next].get('roi') is None:
                    next_undelimited_row = i
                    break
        
        if next_undelimited_row != -1:
            self.list_widget.setCurrentRow(next_undelimited_row)
        
        self.update_details_text()


    def update_report_button_state(self):
        if not self.analysis_stage or not self.analysis_items:
            self.btn_confirm_report.setEnabled(False)
            return
        all_processed = all(item['status'] in ['Confirmado', 'Removido'] for item in self.analysis_items)
        self.btn_confirm_report.setEnabled(all_processed)

    def update_analysis_action_buttons_state(self):
        if not self.analysis_stage or not self.analysis_items:
            is_enabled = False
            for btn_name in ['btn_confirm', 'btn_remove', 'btn_confirm_all', 'btn_remove_all', 
                             'btn_confirm_remaining', 'btn_remove_remaining', 'btn_confirm_report']:
                if hasattr(self, btn_name):
                    getattr(self, btn_name).setEnabled(is_enabled)
            return

        has_unprocessed_items = any(item['status'] is None for item in self.analysis_items)
        
        self.btn_confirm_remaining.setEnabled(has_unprocessed_items)
        self.btn_remove_remaining.setEnabled(has_unprocessed_items)

        self.btn_confirm_all.setEnabled(bool(self.analysis_items))
        self.btn_remove_all.setEnabled(bool(self.analysis_items))

        current_row = self.list_widget.currentRow()
        can_process_current = (0 <= current_row < len(self.analysis_items))
            
        self.btn_confirm.setEnabled(can_process_current)
        self.btn_remove.setEnabled(can_process_current)
        
        self.update_report_button_state()

    def perform_yolo_analysis(self, image_path_to_analyze, output_dir_for_analyzed_image):
        if not self.yolo_model:
            print("Modelo YOLO não carregado. Análise não pode ser realizada.")
            img_pil = Image.open(image_path_to_analyze)
            error_img_path = os.path.join(output_dir_for_analyzed_image, os.path.basename(image_path_to_analyze).replace(".png", "_error.png"))
            img_pil.save(error_img_path)
            return error_img_path, {'total': 0, 'viable': 0, 'inviable': 0}

        try:
            img_to_predict = Image.open(image_path_to_analyze)
            width, height = img_to_predict.size

            results = self.yolo_model.predict(source=image_path_to_analyze, 
                                            imgsz=960, 
                                            conf=0.25,
                                            save=False, 
                                            verbose=False) 

            counts = {'total': 0, 'viable': 0, 'inviable': 0}
            
            if results and results[0].masks is not None: 
                annotated_frame_np = results[0].plot() 
                annotated_frame_pil = Image.fromarray(cv2.cvtColor(annotated_frame_np, cv2.COLOR_BGR2RGB))

                base_name = os.path.splitext(os.path.basename(image_path_to_analyze))[0]
                analyzed_img_name = f"{base_name}_analisada.png"
                analyzed_img_path = os.path.join(output_dir_for_analyzed_image, analyzed_img_name)
                annotated_frame_pil.save(analyzed_img_path)

                detected_classes = results[0].boxes.cls.cpu().numpy() 
                class_names_from_model = results[0].names 

                for cls_idx in detected_classes:
                    class_name = class_names_from_model[int(cls_idx)]
                    if class_name == 'viavel':
                        counts['viable'] += 1
                    elif class_name == 'inviavel':
                        counts['inviable'] += 1
                counts['total'] = counts['viable'] + counts['inviable']
                
                return analyzed_img_path, counts
            else:
                print(f"Nenhuma detecção para {image_path_to_analyze}")
                img_pil = Image.open(image_path_to_analyze)
                no_detection_img_path = os.path.join(output_dir_for_analyzed_image, os.path.basename(image_path_to_analyze).replace(".png", "_no_detection.png"))
                img_pil.save(no_detection_img_path)
                return no_detection_img_path, counts 

        except Exception as e:
            print(f"Erro durante a análise YOLO da imagem {image_path_to_analyze}: {e}")
            traceback.print_exc()
            img_pil = Image.open(image_path_to_analyze)
            error_during_pred_path = os.path.join(output_dir_for_analyzed_image, os.path.basename(image_path_to_analyze).replace(".png", "_pred_error.png"))
            img_pil.save(error_during_pred_path)
            return error_during_pred_path, {'total': 0, 'viable': 0, 'inviable': 0}

    def analyze_images(self):
        valid_image_data_for_analysis = {}
        original_paths_for_analysis = [] 

        for path, data in self.image_data.items():
            is_valid_for_analysis_flag = True
            list_item_text_found = ""
            
            path_basename = os.path.basename(path)
            for i in range(self.list_widget.count()):
                item_text_iter = self.list_widget.item(i).text()
                if path_basename == item_text_iter.split(" [")[0]: 
                    list_item_text_found = item_text_iter
                    break
            
            if '[ERRO]' in list_item_text_found or '[TAMANHO INSUFICIENTE]' in list_item_text_found:
                is_valid_for_analysis_flag = False
            
            if data.get('roi') is None: 
                is_valid_for_analysis_flag = False

            if is_valid_for_analysis_flag:
                valid_image_data_for_analysis[path] = data
                original_paths_for_analysis.append(path)
        
        if not valid_image_data_for_analysis:
            QMessageBox.warning(self, "Aviso", "Nenhuma imagem válida com ROI definida para análise.")
            return

        if not self.yolo_model: 
            QMessageBox.critical(self, "Erro de Modelo", "O modelo YOLO não está carregado. A análise não pode prosseguir.")
            return

        self.statusBar().showMessage("Preparando análise e recortes...")
        QApplication.processEvents()

        base_output_parent_dir = os.path.dirname(original_paths_for_analysis[0]) 
        
        recortes_orig_dir = os.path.join(base_output_parent_dir, 'imagens_recortadas_originais')
        os.makedirs(recortes_orig_dir, exist_ok=True)
        
        yolo_analyzed_output_dir = os.path.join(base_output_parent_dir, 'imagens_recortadas_analisadas')
        os.makedirs(yolo_analyzed_output_dir, exist_ok=True)

        self.analysis_items = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        total_tiles_to_process = len(valid_image_data_for_analysis) * (TILE_COLS * TILE_ROWS)
        processed_tiles_count = 0

        for path, data in valid_image_data_for_analysis.items():
            base_file_name_orig = os.path.basename(path)
            
            pil_original_image = data['pil'] 
            ox, oy, ow, oh = map(int, data['roi'])
            tile_w = ow // TILE_COLS
            tile_h = oh // TILE_ROWS

            for idx in range(TILE_COLS * TILE_ROWS):
                processed_tiles_count += 1
                self.statusBar().showMessage(f"Processando recorte {processed_tiles_count}/{total_tiles_to_process} de {base_file_name_orig}...")
                QApplication.processEvents()

                row = idx // TILE_COLS
                col = idx % TILE_COLS
                left = ox + col * tile_w
                top = oy + row * tile_h

                try:
                    crop = pil_original_image.crop((left, top, left+tile_w, top+tile_h))
                    base_name_no_ext = os.path.splitext(base_file_name_orig)[0]
                    rec_name = f"{base_name_no_ext}_{idx+1}.png"
                    
                    rec_path = os.path.join(recortes_orig_dir, rec_name) 
                    crop.save(rec_path)

                    analyzed_yolo_img_path, counts = self.perform_yolo_analysis(rec_path, yolo_analyzed_output_dir)
                    
                    self.analysis_items.append({
                        'recorte': rec_path,                 
                        'analysed': analyzed_yolo_img_path,  
                        'counts': counts,
                        'status': None
                    })
                except Exception as e:
                    print(f"Erro ao processar tile {idx+1} da imagem {base_file_name_orig}: {e}")
                    traceback.print_exc()
                    error_placeholder_name = f"{os.path.splitext(base_file_name_orig)[0]}_{idx+1}_PROCESSING_ERROR.png"
                    self.analysis_items.append({
                        'recorte': error_placeholder_name, 
                        'analysed': error_placeholder_name, 
                        'counts': {'total': 0, 'viable': 0, 'inviable': 0},
                        'status': 'Erro no Processamento'
                    })


        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage("Análise YOLO concluída. Preparando visualização...")
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
        for item_data in self.analysis_items:
            list_text = os.path.basename(item_data['recorte'])
            if item_data['status'] == 'Erro no Processamento':
                list_text += " [ERRO]" 
            
            list_item_widget = QListWidgetItem(list_text)
            if item_data['status'] == 'Erro no Processamento':
                list_item_widget.setForeground(QColor('magenta')) 
            self.list_widget.addItem(list_item_widget)
        
        try: 
            self.list_widget.currentItemChanged.disconnect()
        except TypeError: 
            pass 
        self.list_widget.currentItemChanged.connect(self.display_selected_item)
        
        if self.list_widget.count() > 0:
            first_valid_analysis_idx = -1
            for i in range(self.list_widget.count()):
                if self.analysis_items[i]['status'] != 'Erro no Processamento':
                    first_valid_analysis_idx = i
                    break
            
            if first_valid_analysis_idx != -1:
                self.list_widget.setCurrentRow(first_valid_analysis_idx)
            elif self.list_widget.count() > 0 : 
                self.list_widget.setCurrentRow(0)
            else: 
                self.scene_orig.clear(); self.scene_analyzed.clear()
                self.update_details_text() 
        else: 
            self.scene_orig.clear(); self.scene_analyzed.clear()
            self.update_details_text() 

        self.update_analysis_action_buttons_state()
        self.activateWindow(); self.list_widget.setFocus()
        self.statusBar().showMessage("Pronto para revisão da análise.")

    def confirm_current_analysis(self):
        idx = self.list_widget.currentRow()
        if idx < 0 or idx >= len(self.analysis_items): return
        
        self.analysis_items[idx]['status'] = 'Confirmado'
        itm = self.list_widget.item(idx)
        base_name = os.path.basename(self.analysis_items[idx]['recorte'])
        new_text = f"{base_name} [C]"
        if itm.text() != new_text: 
            itm.setText(new_text)
        
        self.update_details_text() 
        self.next_analysis() 
        self.update_analysis_action_buttons_state()


    def remove_current_analysis(self):
        idx = self.list_widget.currentRow()
        if idx < 0 or idx >= len(self.analysis_items): return

        self.analysis_items[idx]['status'] = 'Removido'
        itm = self.list_widget.item(idx)
        base_name = os.path.basename(self.analysis_items[idx]['recorte'])
        new_text = f"{base_name} [R]"
        if itm.text() != new_text: 
            itm.setText(new_text)

        self.update_details_text() 
        self.next_analysis() 
        self.update_analysis_action_buttons_state()

    def next_analysis(self): # Used by confirm/remove in analysis stage
        current_idx = self.list_widget.currentRow()
        if len(self.analysis_items) == 0: return 

        for i in range(current_idx + 1, len(self.analysis_items)):
            if self.analysis_items[i]['status'] is None:
                self.list_widget.setCurrentRow(i)
                return
        for i in range(current_idx): 
            if self.analysis_items[i]['status'] is None:
                self.list_widget.setCurrentRow(i)
                return
        
        self.update_analysis_action_buttons_state()


    def confirm_all(self):
        if not self.analysis_items: return
        for i, it in enumerate(self.analysis_items):
            it['status'] = 'Confirmado'
            list_item = self.list_widget.item(i)
            base_name = os.path.basename(it['recorte'])
            list_item.setText(f"{base_name} [C]") 
        self.update_analysis_action_buttons_state()
        self.update_details_text() 

    def remove_all(self):
        if not self.analysis_items: return
        for i, it in enumerate(self.analysis_items):
            it['status'] = 'Removido'
            list_item = self.list_widget.item(i)
            base_name = os.path.basename(it['recorte'])
            list_item.setText(f"{base_name} [R]") 
        self.update_analysis_action_buttons_state()
        self.update_details_text() 

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
            
            base_dir = self.default_directory 

            if self.processed_files_base_dir: 
                base_dir = self.processed_files_base_dir
            elif self.image_paths: 
                base_dir = os.path.dirname(self.image_paths[0])
            elif not os.path.isdir(base_dir): 
                 QMessageBox.critical(self, "Erro", "Não foi possível determinar um diretório válido para salvar o relatório.")
                 return

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
        <li><b>Carregamento de Imagens Originais (para delimitação):</b>
            <ul>
                <li>Clique em "Selecionar Arquivos" ou "Selecionar Pasta".</li>
                <li>Imagens muito pequenas (menores que {W}x{H} pixels) ou corrompidas serão marcadas e não poderão ser delimitadas.</li>
            </ul>
        </li>
        <li><b>Carregamento de Imagens Já Processadas (recortadas):</b>
            <ul>
                <li>Clique em "Selecionar Arquivos Processados" ou "Selecionar Pasta Processada".</li>
                <li>As imagens devem ter dimensões de {PW}x{PH} pixels. Imagens com dimensões incorretas serão marcadas com erro e não serão analisadas.</li>
                <li>Este modo pula a etapa de delimitação e vai direto para a análise.</li>
            </ul>
        </li>
        <li><b>Navegação:</b> Use as teclas de seta (Cima/Baixo) ou o scroll do mouse sobre a área da imagem para navegar entre os itens da lista em ambas as fases.</li>
        <li><b>Fase de Delimitação (apenas para imagens originais):</b>
            <ul>
                <li>Posicione o retângulo vermelho sobre a área desejada na imagem grande.</li>
                <li>Clique em "Delimitar [D]" (ou use Enter/Ctrl+D).</li>
                <li>Repita para todas as imagens válidas. O programa tentará selecionar a próxima imagem não delimitada na sequência.</li>
                <li>Após todas as imagens válidas serem delimitadas, o botão "Analisar Imagens" ficará disponível.</li>
            </ul>
        </li>
        <li><b>Fase de Análise (automática após delimitação ou ao carregar imagens processadas):</b>
            <ul>
                <li>Se partiu de imagens originais, elas serão recortadas em seções ({TC} colunas x {TR} linhas).</li>
                <li>Cada seção (ou cada imagem processada carregada) passará pela análise do modelo YOLOv8.</li>
                <li>O modelo identificará sementes viáveis e inviáveis, e uma imagem com as detecções será gerada.</li>
                <li>Você verá o recorte original (ou a imagem processada) e a imagem analisada pela YOLO lado a lado.</li>
            </ul>
        </li>
        <li><b>Revisão da Análise:</b>
            <ul>
                <li>Selecione uma seção analisada na lista.</li>
                <li>Clique em "Confirmar [C]" (ou Ctrl+C) ou "Remover [R]" (ou Ctrl+R) para marcar/alterar seu status. O programa tentará selecionar a próxima seção não processada.</li>
                <li>Use "Confirmar Todas", "Remover Todas", "Confirmar Restantes" ou "Remover Restantes" para ações em lote.</li>
            </ul>
        </li>
        <li><b>Gerar Relatório:</b>
            <ul>
                <li>Preencha os campos obrigatórios no topo da janela: "Análise", "Espécie", "Temp. Armazenamento (°C)", "Tempo (h)".</li>
                <li>Após todas as seções analisadas terem sido Confirmadas ou Removidas, clique em "Confirmar e Gerar Relatório".</li>
                <li>O relatório CSV será salvo no diretório das imagens originais ou no diretório das imagens processadas carregadas.</li>
            </ul>
        </li>
        </ol>
        
        <p><b>Atalhos de teclado:</b> Enter/Ctrl+D (Delimitar), Ctrl+C (Confirmar), Ctrl+R (Remover).</p>
        """.format(
            W=TARGET_RECT_WIDTH_ORIGINAL, H=TARGET_RECT_HEIGHT_ORIGINAL,
            PW=EXPECTED_PROCESSED_WIDTH, PH=EXPECTED_PROCESSED_HEIGHT,
            TC=TILE_COLS, TR=TILE_ROWS
        )
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Ajuda")
        msg.setTextFormat(Qt.TextFormat.RichText) # Permite HTML básico
        msg.setText(help_text)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = SeedAnalyzerApp()
    win.showMaximized()
    sys.exit(app.exec())