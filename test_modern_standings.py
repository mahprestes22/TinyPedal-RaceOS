"""
Protótipo Visual - Standings Moderno (Dark Glass / WEC Style)
Desenvolvido para demonstração visual no TinyPedal
"""
import sys
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QLinearGradient, QBrush, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

class ModernRowWidget(QWidget):
    def __init__(self, pos, cls_name, cls_color, car_no, driver_name, car_name, gap, dr_rating, dr_delta, is_player=False, parent=None):
        super().__init__(parent)
        self.pos = pos
        self.cls_name = cls_name
        self.cls_color = QColor(cls_color)
        self.car_no = car_no
        self.driver_name = driver_name
        self.car_name = car_name
        self.gap = gap
        self.dr_rating = dr_rating
        self.dr_delta = dr_delta
        self.is_player = is_player
        self.setFixedHeight(30)
        self.setMinimumWidth(640)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # 1. Fundo com degradê translúcido (Dark Glass)
        grad = QLinearGradient(0, 0, w, 0)
        if self.is_player:
            # Destaque suave em tom azul/ciano para o jogador
            grad.setColorAt(0.0, QColor(0, 150, 255, 140))
            grad.setColorAt(0.4, QColor(18, 28, 52, 225))
            grad.setColorAt(1.0, QColor(12, 16, 28, 210))
        else:
            grad.setColorAt(0.0, QColor(26, 30, 42, 220))
            grad.setColorAt(0.5, QColor(18, 22, 32, 210))
            grad.setColorAt(1.0, QColor(14, 16, 24, 200))

        painter.setBrush(QBrush(grad))
        if self.is_player:
            painter.setPen(QPen(QColor(0, 210, 255, 200), 1))
        else:
            painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
        painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 4, 4)

        # 2. Barra luminosa lateral para o jogador
        if self.is_player:
            bar_grad = QLinearGradient(0, 0, 0, h)
            bar_grad.setColorAt(0.0, QColor(0, 230, 255, 255))
            bar_grad.setColorAt(1.0, QColor(0, 120, 255, 255))
            painter.fillRect(1, 2, 4, h - 4, QBrush(bar_grad))

        # 3. Posição (P1, P2...)
        font_pos = QFont("Segoe UI", 10, QFont.Bold)
        painter.setFont(font_pos)
        painter.setPen(QColor(240, 240, 245) if not self.is_player else QColor(0, 220, 255))
        painter.drawText(QRectF(10, 0, 28, h), Qt.AlignVCenter | Qt.AlignLeft, f"P{self.pos}")

        # 4. Badge da Categoria (HY, LMP2, GT3) com pílula arredondada e degradê
        badge_rect = QRectF(42, 5, 46, h - 10)
        badge_grad = QLinearGradient(badge_rect.left(), 0, badge_rect.right(), 0)
        badge_grad.setColorAt(0.0, self.cls_color)
        badge_grad.setColorAt(1.0, self.cls_color.darker(130))
        painter.setBrush(QBrush(badge_grad))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(badge_rect, 3, 3)

        font_badge = QFont("Segoe UI", 8, QFont.Bold)
        painter.setFont(font_badge)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(badge_rect, Qt.AlignCenter, self.cls_name)

        # 5. Número do Carro
        font_no = QFont("Consolas", 9, QFont.Bold)
        painter.setFont(font_no)
        painter.setPen(QColor(180, 190, 205))
        painter.drawText(QRectF(94, 0, 26, h), Qt.AlignVCenter | Qt.AlignCenter, f"#{self.car_no}")

        # 6. Nome do Piloto
        font_name = QFont("Segoe UI", 9, QFont.Bold if self.is_player else QFont.Normal)
        painter.setFont(font_name)
        painter.setPen(QColor(255, 255, 255) if self.is_player else QColor(225, 230, 240))
        painter.drawText(QRectF(126, 0, 160, h), Qt.AlignVCenter | Qt.AlignLeft, self.driver_name)

        # 7. Modelo do Carro
        font_car = QFont("Segoe UI", 8)
        painter.setFont(font_car)
        painter.setPen(QColor(135, 145, 165))
        painter.drawText(QRectF(290, 0, 130, h), Qt.AlignVCenter | Qt.AlignLeft, self.car_name)

        # 8. Intervalo / Gap
        font_mono = QFont("Consolas", 9, QFont.Bold)
        painter.setFont(font_mono)
        painter.setPen(QColor(255, 215, 0) if self.pos == 1 else QColor(200, 205, 215))
        painter.drawText(QRectF(425, 0, 75, h), Qt.AlignVCenter | Qt.AlignRight, self.gap)

        # 9. Integração Nakama: DR (Driver Rating)
        font_dr = QFont("Segoe UI", 8)
        painter.setFont(font_dr)
        painter.setPen(QColor(165, 180, 200))
        painter.drawText(QRectF(510, 0, 70, h), Qt.AlignVCenter | Qt.AlignRight, self.dr_rating)

        # 10. Delta de DR (▲ +15 em verde / ▼ -8 em vermelho)
        font_delta = QFont("Segoe UI", 8, QFont.Bold)
        painter.setFont(font_delta)
        if self.dr_delta.startswith("+"):
            painter.setPen(QColor(46, 204, 113)) # Verde
        elif self.dr_delta.startswith("-"):
            painter.setPen(QColor(231, 76, 60))  # Vermelho
        else:
            painter.setPen(QColor(150, 150, 150))
        painter.drawText(QRectF(585, 0, 50, h), Qt.AlignVCenter | Qt.AlignRight, self.dr_delta)


class ModernStandingsWidget(QWidget):
    def __init__(self):
        super().__init__()
        # Configuração de Janela Transparente de Overlay (Always on top)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("LMU Modern Standings Overlay")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(3)

        # Cabeçalho da Tabela
        header = QWidget()
        header.setFixedHeight(26)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(6, 0, 6, 0)

        title = QLabel("🏁 LMU CLASSIFICAÇÃO EM TEMPO REAL — 6H DE SPA")
        title.setFont(QFont("Segoe UI", 8, QFont.Bold))
        title.setStyleSheet("color: rgba(200, 220, 250, 0.9); letter-spacing: 1px;")
        h_layout.addWidget(title)
        h_layout.addStretch()

        hint = QLabel("(Arraste para mover)")
        hint.setFont(QFont("Segoe UI", 8))
        hint.setStyleSheet("color: rgba(140, 160, 190, 0.6);")
        h_layout.addWidget(hint)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(20, 20)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 20);
                color: #aaa;
                border: none;
                border-radius: 10px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(230, 50, 50, 200);
                color: #fff;
            }
        """)
        btn_close.clicked.connect(self.close)
        h_layout.addWidget(btn_close)

        layout.addWidget(header)

        # Dados Simulados (Mock Data do grid WEC / LMU)
        grid_data = [
            (1, "HY", "#E10600", "51", "A. Pier Guidi", "Ferrari 499P", "LÍDER", "Plat 1", "+24", False),
            (2, "HY", "#E10600", "6", "K. Estre", "Porsche 963", "+1.240", "Gold 2", "+18", False),
            (3, "HY", "#E10600", "2", "E. Bamber", "Cadillac V-Series", "+3.890", "Gold 1", "+11", False),
            (4, "HY", "#E10600", "83", "VOCÊ (Piloto)", "Ferrari 499P", "+4.120", "Gold 3", "+15", True), # O jogador
            (5, "HY", "#E10600", "8", "S. Buemi", "Toyota GR010", "+7.450", "Gold 1", "-4", False),
            (6, "LMP2", "#0078D7", "22", "P. Albuquerque", "Oreca 07", "+24.500", "Silver 1", "+19", False),
            (7, "LMP2", "#0078D7", "41", "R. Andrade", "Oreca 07", "+25.100", "Silver 2", "+12", False),
            (8, "GT3", "#FF8C00", "92", "K. Bachler", "Porsche 911 GT3", "+1 Lap", "Silver 3", "+14", False),
            (9, "GT3", "#FF8C00", "46", "V. Rossi", "BMW M4 GT3", "+1 Lap", "Bronze 1", "-8", False),
        ]

        for item in grid_data:
            row = ModernRowWidget(*item)
            layout.addWidget(row)

        self.old_pos = None

    def paintEvent(self, event):
        # Fundo Dark Glass translúcido para todo o container
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        bg_rect = QRectF(2, 2, w - 4, h - 4)

        card_grad = QLinearGradient(0, 0, 0, h)
        card_grad.setColorAt(0.0, QColor(10, 12, 18, 230))
        card_grad.setColorAt(1.0, QColor(6, 8, 12, 240))
        painter.setBrush(QBrush(card_grad))
        painter.setPen(QPen(QColor(255, 255, 255, 25), 1))
        painter.drawRoundedRect(bg_rect, 8, 8)

    # Permitir arrastar a janela com o botão esquerdo do mouse
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.old_pos is not None:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.old_pos = None


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ModernStandingsWidget()
    window.resize(680, 380)

    # Centralizar na tela principal
    screen_geo = QGuiApplication.primaryScreen().availableGeometry()
    x = (screen_geo.width() - window.width()) // 2
    y = (screen_geo.height() - window.height()) // 2
    window.move(x, y)

    window.show()
    sys.exit(app.exec())
