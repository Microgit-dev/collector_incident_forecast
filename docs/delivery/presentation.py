"""
Презентация решения на шаблоне конкурса «Лидеры цифровой трансформации 2026» (data/ЛЦТ2026 Шаблон
презентации.pptx) → docs/delivery/out/Презентация.pptx.

Обязательные слайды шаблона 7–11 заполняются в исходных фигурах (дизайн и сетка не меняются, на слайде
команды лишние карточки удаляются). Описательная часть — свои слайды на макетах шаблона: белые
карточки, розовые плашки заголовков, BPMN-схемы процессов и схема ML-конвейера нативными фигурами
PowerPoint (их можно править).

Данные команды — в TEAM ниже (заполняются перед сдачей).

    uv run --no-project --with python-pptx --with pywin32 python docs/delivery/presentation.py
"""

from __future__ import annotations

import copy
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Cm, Pt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TEMPLATE = ROOT / "data" / "ЛЦТ2026 Шаблон презентации.pptx"
OUT = HERE / "out" / "Презентация.pptx"
IMG = HERE / "img"
LOGO_DZHKH = "Image 8"  # «Департамент жилищно-коммунального хозяйства города Москвы» со слайда 6 шаблона

PINK = RGBColor(0xFF, 0x00, 0x53)
PINK_LIGHT = RGBColor(0xFF, 0xD6, 0xE4)
LAVENDER = RGBColor(0x8A, 0x83, 0xD1)
DARK = RGBColor(0x31, 0x0F, 0x53)
PURPLE = RGBColor(0x52, 0x09, 0x78)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
INK = RGBColor(0x1C, 0x1D, 0x22)
GREY = RGBColor(0x6B, 0x6B, 0x7B)
LANE = RGBColor(0xF3, 0xF0, 0xFA)
FONT = "Montserrat"

# ---------------------------------------------------------------- данные команды (заполнить перед сдачей)
TEAM = {
    "name": "[Название команды]",
    "captain": "[ФИО капитана, специальность]",
    "size": "[N]",
    "about": "[как образовалась команда; место работы или учёбы участников]",
    "city": "[город и регион]",
    "history": "[Краткая история команды: как собрались, участвовали ли вместе в хакатонах или проектах]",
    "members": [
        # {"name": "Имя Фамилия", "role": "...", "nick": "@...", "phone": "+7 ...", "work": "..."},
        {"name": "[Имя Фамилия]", "role": "[роль в команде]", "nick": "[ник]", "phone": "[телефон]", "work": "[место работы/учёбы]"},
    ],
}

# ---------------------------------------------------------------- базовые элементы


def _font(run, size=None, bold=None, color=None, name=FONT):
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    run.font.name = name


def text(slide, x, y, w, h, lines, size=12, color=INK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.0):
    """Текстовое поле. lines — строки; «• » в начале — пункт списка; («текст», {"bold": True, …}) — стиль строки."""
    box = slide.shapes.add_textbox(Cm(x), Cm(y), Cm(w), Cm(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Cm(0.1)
    tf.margin_top = tf.margin_bottom = Cm(0.05)
    for i, line in enumerate(lines):
        style = {}
        if isinstance(line, tuple):
            line, style = line
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = style.get("align", align)
        para.line_spacing = spacing
        if style.get("space"):
            para.space_before = Pt(style["space"])
        run = para.add_run()
        run.text = line
        _font(run, style.get("size", size), style.get("bold", bold), style.get("color", color))
    return box


def rect(slide, x, y, w, h, fill=WHITE, line=None, radius=0.08, shape=MSO_SHAPE.ROUNDED_RECTANGLE, line_width=1.0):
    s = slide.shapes.add_shape(shape, Cm(x), Cm(y), Cm(w), Cm(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(line_width)
    s.shadow.inherit = False
    s.text_frame.margin_left = s.text_frame.margin_right = Cm(0.15)
    return s


def label(shape, lines, size=11, color=INK, bold=False, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE):
    tf = shape.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for i, line in enumerate(lines):
        style = {}
        if isinstance(line, tuple):
            line, style = line
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = style.get("align", align)
        run = para.add_run()
        run.text = line
        _font(run, style.get("size", size), style.get("bold", bold), style.get("color", color))
    return shape


def header(slide, title, color=PINK):
    """Плашка заголовка слайда, как в шаблоне: скруглённый прямоугольник, белый заглавный текст."""
    width = min(16.0, 1.6 + 0.42 * len(title))
    pill = rect(slide, 1.0, 0.9, width, 1.5, fill=color, radius=0.3)
    label(pill, [title.upper()], size=16, color=WHITE, bold=True)
    return pill


def card(slide, x, y, w, h, title=None, lines=(), size=12.5, title_color=PURPLE, fill=WHITE):
    rect(slide, x, y, w, h, fill=fill, radius=0.06)
    top = y + 0.35
    if title:
        text(slide, x + 0.4, top, w - 0.8, 1.0, [title], size=14, bold=True, color=title_color)
        top += 1.2
    if lines:
        text(slide, x + 0.4, top, w - 0.8, h - (top - y) - 0.2, list(lines), size=size, color=INK)


def picture(slide, path, x, y, w=None, h=None, frame=True):
    pic = slide.shapes.add_picture(str(path), Cm(x), Cm(y), Cm(w) if w else None, Cm(h) if h else None)
    if frame:
        border = rect(slide, x - 0.15, y - 0.15, pic.width / 360000 + 0.3, pic.height / 360000 + 0.3, fill=WHITE, radius=0.02)
        pic._element.addprevious(border._element)
    return pic


def arrow(slide, a, b, a_side="right", b_side="left", color=PURPLE, width=1.5, elbow=True, dash=False):
    """Стрелка между фигурами (точки соединения: top 0, left 1, bottom 2, right 3)."""
    sides = {"top": 0, "left": 1, "bottom": 2, "right": 3}
    conn = slide.shapes.add_connector(MSO_CONNECTOR.ELBOW if elbow else MSO_CONNECTOR.STRAIGHT, 0, 0, 0, 0)
    conn.begin_connect(a, sides[a_side])
    conn.end_connect(b, sides[b_side])
    conn.line.color.rgb = color
    conn.line.width = Pt(width)
    ln = conn.line._get_or_add_ln()
    if dash:
        prst = etree.SubElement(ln, qn("a:prstDash"))
        prst.set("val", "dash")
    tail = etree.SubElement(ln, qn("a:tailEnd"))
    tail.set("type", "triangle")
    tail.set("w", "med")
    tail.set("len", "med")
    return conn


def new_slide(prs, layout="Пустой"):
    lay = next(lay for lay in prs.slide_layouts if lay.name == layout)
    slide = prs.slides.add_slide(lay)
    for ph in list(slide.placeholders):
        if ph.placeholder_format.type not in (13,):  # оставляем только номер слайда
            ph._element.getparent().remove(ph._element)
    return slide


def delete_slide(prs, slide):
    sld_ids = prs.slides._sldIdLst
    for sld_id in list(sld_ids):
        if prs.part.related_part(sld_id.rId) is slide.part:
            prs.part.drop_rel(sld_id.rId)
            sld_ids.remove(sld_id)
            return


def set_lines(shape, lines):
    """Заменить текст фигуры шаблона, сохранив оформление первого абзаца и первого прогона."""
    tf = shape.text_frame
    first = tf.paragraphs[0]
    template_p = copy.deepcopy(first._p)
    for p in list(tf.paragraphs)[1:]:
        p._p.getparent().remove(p._p)
    for i, line in enumerate(lines):
        bold = None
        if isinstance(line, tuple):
            line, bold = line
        if i == 0:
            p = first
        else:
            new_p = copy.deepcopy(template_p)
            first._p.getparent().append(new_p)
            p = tf.paragraphs[-1]
        runs = p.runs
        if runs:
            runs[0].text = line
            for r in runs[1:]:
                r._r.getparent().remove(r._r)
            if bold is not None:
                runs[0].font.bold = bold
        else:
            run = p.add_run()
            run.text = line


def by_text(slide, startswith):
    for sh in slide.shapes:
        if sh.has_text_frame and sh.text_frame.text.strip().startswith(startswith):
            return sh
    raise KeyError(startswith)


# ---------------------------------------------------------------- обязательные слайды 7–11


def fill_mandatory(prs):
    slides = list(prs.slides)
    title, about, team, story, brief = slides[6:11]

    # 7 — титул: название команды, задача, логотип постановщика
    logo = next(sh for sh in slides[5].shapes if sh.name == LOGO_DZHKH)
    for ph in title.placeholders:
        idx = ph.placeholder_format.idx
        if idx == 0:
            ph.text_frame.text = TEAM["name"]
        elif idx == 12:
            ph.text_frame.text = (
                "Задача 8 ДЖКХ: сервис прогнозирования инцидентов и управления ремонтными работами "
                "инженерных коллекторов Москвы"
            )
        elif idx == 11:
            x, y, w, h = ph.left, ph.top, ph.width, ph.height
            ph._element.getparent().remove(ph._element)
            pic = title.shapes.add_picture(io_bytes(logo.image.blob), x, y + Cm(0.3), height=h - Cm(0.6))
            if pic.width > w:
                ratio = w / pic.width
                pic.width, pic.height = int(pic.width * ratio), int(pic.height * ratio)

    # 8 — о команде, суть и уникальность
    set_lines(by_text(about, "Капитан"), [
        (f"Капитан: {TEAM['captain']}", True),
        (f"Кол-во участников: {TEAM['size']} человек", True),
        ("Краткое описание: ", True),
        (TEAM["about"], False),
        (f"Город и регион: {TEAM['city']}", True),
    ])
    set_lines(by_text(about, "В чем суть"), [
        "Сервис превращает поток сырых сигналов СМВУ в приоритизированные риски: прогнозирует отказы "
        "датчиков, газ и подтопление на 24 ч, объясняет причины, предлагает действие, ведёт решение "
        "диспетчера до заявки бригаде и учится на результате. Инженер ТО планирует профилактику "
        "по регламенту и фактическому состоянию."
    ])
    set_lines(by_text(about, "Что делает ваше"), [
        "47 тревог → 1 карточка с гипотезой причины и чек-листом. Прогноз честно проверен на отложенном "
        "2026 годе, генератор графиков ТО сверен с реальными графиками заказчика, новые датчики "
        "подключаются конструктором без программиста."
    ])
    for ph in about.placeholders:
        if ph.placeholder_format.idx == 0:
            ph.text_frame.text = "Прогноз инцидентов коллекторов"
            for run in ph.text_frame.paragraphs[0].runs:
                run.font.color.rgb = PURPLE
        elif ph.placeholder_format.idx == 10:
            x, y, w, h = ph.left, ph.top, ph.width, ph.height
            pic = ph.insert_picture(str(IMG / "workspace.png"))
            pic.left, pic.top, pic.width, pic.height = x, y, w, h

    # 9 — карточки участников: лишние удаляются
    members = TEAM["members"]
    names = [sh for sh in team.shapes if sh.has_text_frame and sh.text_frame.text.strip() == "Имя Фамилия"]
    infos = [sh for sh in team.shapes if sh.has_text_frame and sh.text_frame.text.strip().startswith("Роль в команде")]
    cards = [sh for sh in team.shapes if sh.name.startswith("Скругленный прямоугольник") and sh.height > Cm(10)]
    pics = [sh for sh in team.placeholders if sh.placeholder_format.type == 18]
    key = lambda s: s.left  # noqa: E731
    names, infos, cards, pics = (sorted(v, key=key) for v in (names, infos, cards, pics))
    for i in range(len(cards)):
        if i < len(members):
            m = members[i]
            set_lines(names[i], [m["name"]])
            set_lines(infos[i], [m["role"], m["nick"], m["phone"], m["work"]])
        else:
            for sh in (names[i], infos[i], cards[i], pics[i]):
                sh._element.getparent().remove(sh._element)
    for ph in team.placeholders:
        if ph.placeholder_format.idx == 0:
            ph.text_frame.text = "КОМАНДА"

    # 10 — история, выбор задачи, сложности
    set_lines(by_text(story, "Расскажите, как вы собрались"), [TEAM["history"]])
    set_lines(by_text(story, "Что вас вдохновило"), [
        "Реальные данные города — 14 ГБ журналов СМВУ за 8 лет — и задача, где польза видна сразу: "
        "меньше ложных выездов, ТО по состоянию, понятная причина каждой тревоги."
    ])
    set_lines(by_text(story, "Расскажите о самых интересных"), [
        "Данные без меток: отказы — служебные коды и «1970-01-01», тревоги в основном ложные, пожаров нет. "
        "Вывели слабые метки из журналов, для пожара и НСД — правила с вероятностью по истории, "
        "проверка — только на отложенном 2026 годе. Каскады по сотне каналов за секунду — склейка в эпизоды.",
    ])
    for ph in story.placeholders:
        if ph.placeholder_format.idx == 0:
            ph.text_frame.text = "О КОМАНДЕ И ЗАДАЧЕ"

    # 11 — коротко о решении
    set_lines(by_text(brief, "Опишите в чем техническая"), [
        "Поток СМВУ (Kafka) → нормализация по профилям датчиков → TimescaleDB и Parquet-архив",
        "LightGBM: отказ датчика, метан ≥ 1 %, подтопление на 24 ч; пожар и НСД — правила с вероятностью "
        "по архиву",
        "Склейка сигналов в эпизоды (×42), гипотезы причины, операционный приоритет",
        "Django/DRF, React, Celery, Redis, Grafana; 8 ролей RBAC, LDAP/AD, TLS",
        "Конструктор форматов; адаптеры help desk, реестра, видеонаблюдения",
    ])
    set_lines(by_text(brief, "Опишите ваши идеи"), [
        "ОДС и подразделения: меньше ложных выездов, очередь по опасности, проверка по камерам",
        "Эксплуатация: план ТО по регламенту и состоянию, графики ТО и ППР в формах заказчика",
        "Внедрение: одна команда развёртывания, закрытый контур, системы заказчика — режимом в .env",
        "Тиражирование: любые коллекторы и датчики — шаблоном и профилем, без доработки кода",
    ])


def io_bytes(blob):
    import io

    return io.BytesIO(blob)


# ---------------------------------------------------------------- описательная часть


def slide_problem(prs):
    s = new_slide(prs)
    header(s, "Проблема и данные")
    card(s, 1.0, 3.2, 10.2, 7.2, "Реактивная работа", [
        "• Реагирование только после срабатывания датчика",
        "• 90 250 сигналов за 30 суток на 95 объектах — диспетчер тонет в потоке",
        "• Каскады: сотня тревог за одну секунду от одного отказа питания или связи",
    ])
    card(s, 11.8, 3.2, 10.2, 7.2, "Ложные тревоги", [
        "• Большая часть тревог дымовых и охранных извещателей — ложные",
        "• Выезды «на всякий случай» и усталость от тревог",
        "• Подтверждённых пожаров и проникновений в данных нет",
    ])
    card(s, 22.6, 3.2, 10.2, 7.2, "ТО по календарю", [
        "• Обслуживание по фиксированным срокам, без учёта состояния",
        "• Графики ТО и ППР ведутся вручную в XLSX",
        "• Пиковые месяцы: до 62 работ по графику против 33 в спокойные",
    ])
    rect(s, 1.0, 11.0, 31.8, 6.6, fill=DARK, radius=0.05)
    text(s, 1.6, 11.4, 30.6, 1.0, ["Данные заказчика, с которыми работает решение"], size=14, bold=True, color=WHITE)
    stats = [("14 ГБ", "журналов СМВУ\n2019–2026 (без 2021)"), ("11 485", "каналов данных\n19 типов датчиков"),
             ("95", "объектов района\n(дерево объектов)"), ("1 008", "датчиков метана\nв ППР на 2026 год"),
             ("24", "объекта в графике\nТО и ТР на 2026 год")]
    for i, (big, small) in enumerate(stats):
        x = 1.6 + i * 6.2
        text(s, x, 12.6, 5.8, 1.6, [big], size=30, bold=True, color=PINK)
        text(s, x, 14.4, 5.8, 2.4, small.split("\n"), size=11, color=WHITE)


def slide_cycle(prs):
    s = new_slide(prs)
    header(s, "Решение: замкнутый цикл")
    steps = [
        ("Предсказать", "LightGBM на 24 ч: отказ датчика, метан, подтопление; индикаторы пожара и НСД"),
        ("Объединить", "Сигналы → эпизод: каскад по питанию и связи — одна карточка"),
        ("Приоритизировать", "Вероятность × тяжесть × критичность × срочность × уверенность данных"),
        ("Объяснить", "Факторы SHAP, гипотезы причины, история канала, похожие случаи"),
        ("Предложить действие", "Чек-лист, камеры у места тревоги, черновик заявки, ТО по состоянию"),
        ("Получить результат", "Решение диспетчера, отчёт и состояние оборудования от бригады"),
        ("Улучшить модель", "Метки из решений, проверка аналитиком, переобучение раз в неделю"),
    ]
    boxes = []
    for i, (title, desc) in enumerate(steps):
        x = 1.0 + i * 4.6
        b = rect(s, x, 4.2, 4.1, 2.2, fill=PINK if i in (0, 6) else WHITE, radius=0.15)
        label(b, [title], size=12, bold=True, color=WHITE if i in (0, 6) else PURPLE)
        boxes.append(b)
        rect(s, x, 7.0, 4.1, 6.0, fill=WHITE, radius=0.06)
        text(s, x + 0.25, 7.3, 3.6, 5.5, [desc], size=12, color=INK)
    for a, b in zip(boxes, boxes[1:]):
        arrow(s, a, b, elbow=False, color=WHITE, width=2)
    rect(s, 1.0, 13.8, 31.8, 3.8, fill=DARK, radius=0.06)
    text(s, 1.6, 14.1, 30.6, 3.4, [
        ("Главная демонстрация", {"bold": True, "color": PINK, "size": 13}),
        ("47 тревог на объекте → 1 карточка, 3 гипотезы причины, 1 действие, 1 черновик заявки. "
         "Система не принимает решений за диспетчера (ТЗ §5): она показывает риск, его причины и "
         "предлагает действие, а решение человека возвращается в систему как обратная связь.", {"color": WHITE}),
    ], size=12)


def slide_features(prs):
    s = new_slide(prs)
    header(s, "Функции")
    features = [
        ("Мониторинг", "Карта зоны на OSM: объекты в цвете обстановки, риска, данных, заявок"),
        ("Эпизоды", "Склейка сигналов ×42, гипотезы причины, чек-лист, приоритет 0–100"),
        ("Прогноз", "Отказ датчика, метан, подтопление на 24 ч; журнал с исходами"),
        ("Пожар и НСД", "Индекс правил + вероятность по истории 10 175 и 73 811 случаев"),
        ("Проверка по камерам", "Ближайшие камеры, кадр на момент тревоги, запись в хронологию"),
        ("Заявки", "Черновик → утверждение → help desk → бригада → отчёт и состояние"),
        ("Инженер ТО", "План по регламенту и состоянию, реестр, осмотры, выгрузка плана"),
        ("Графики ТО и ППР", "В формах заказчика; сверка с его графиками: периодичность 91 %"),
        ("Конструктор", "Новые форматы датчиков шаблоном: JSON, CSV, строка; песочница"),
        ("Обучение моделей", "Метки из решений, проверка аналитиком, чемпион / претендент"),
        ("Аналитика", "Эффективность диспетчеров, «кто первый», качество прогнозов, PDF/XLSX"),
        ("Учения и обучение", "Учебный контур с симулятором, учения с разбором, задания по ролям"),
    ]
    for i, (title, desc) in enumerate(features):
        col, row = i % 4, i // 4
        x, y = 1.0 + col * 8.0, 3.2 + row * 4.9
        rect(s, x, y, 7.6, 4.5, fill=WHITE, radius=0.06)
        rect(s, x + 0.4, y + 0.45, 0.35, 0.35, fill=PINK, shape=MSO_SHAPE.OVAL)
        text(s, x + 0.95, y + 0.25, 6.4, 0.9, [title], size=14, bold=True, color=PURPLE)
        text(s, x + 0.4, y + 1.35, 6.8, 3.0, [desc], size=12.5, color=INK)


def slide_roles(prs):
    s = new_slide(prs)
    header(s, "8 ролей — 8 рабочих мест")
    roles = [
        ("Диспетчер ОДС", "весь район: карточки, решения, заявки"),
        ("Диспетчер подразделения", "то же в своей зоне, камеры"),
        ("Руководитель", "эскалации, перехват, утверждение, учения"),
        ("Аналитик", "метки, модели, данные, конструктор"),
        ("Инженер ТО", "план ТО, реестр, графики ТО и ППР"),
        ("Ремонтная бригада", "свои заявки с телефона, состояние"),
        ("Наблюдатель", "просмотр обстановки зоны"),
        ("Администратор", "роли, интеграции, мониторинг"),
    ]
    for i, (role, what) in enumerate(roles):
        y = 3.2 + i * 1.8
        rect(s, 1.0, y, 11.6, 1.55, fill=WHITE, radius=0.12)
        text(s, 1.4, y + 0.12, 11.0, 0.7, [role], size=12, bold=True, color=PURPLE)
        text(s, 1.4, y + 0.78, 11.0, 0.7, [what], size=10, color=GREY)
    picture(s, IMG / "guides" / "engineer_1_workspace.png", 13.6, 3.3, w=18.8)
    text(s, 13.6, 15.5, 19.0, 3.0, [
        ("Зона ответственности и командная вертикаль", {"bold": True, "color": WHITE, "size": 13}),
        ("Каждый видит только свою зону; карточку забирает тот, кто первым откликнулся; без реакции в "
         "норматив (5 мин для критических) карточка поднимается на уровень выше. Руководства "
         "пользователя — отдельно для каждой роли.", {"color": WHITE}),
    ], size=11)


def _lanes(s, x, y, w, lanes, lane_h, title_w=3.2):
    rect(s, x, y, w, lane_h * len(lanes), fill=WHITE, radius=0.02)
    for i, name in enumerate(lanes):
        ly = y + i * lane_h
        band = rect(s, x, ly, title_w, lane_h, fill=LANE if i % 2 == 0 else WHITE, line=LAVENDER, radius=0.0,
                    shape=MSO_SHAPE.RECTANGLE, line_width=0.5)
        label(band, [name], size=10, bold=True, color=PURPLE)
        if i:
            line = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Cm(x), Cm(ly), Cm(x + w), Cm(ly))
            line.line.color.rgb = LAVENDER
            line.line.width = Pt(0.5)


def _task(s, x, y, text_, w=3.4, h=1.5, fill=PINK_LIGHT):
    b = rect(s, x, y, w, h, fill=fill, line=PURPLE, radius=0.18, line_width=1.0)
    label(b, [text_], size=10, color=INK)
    return b


def _event(s, x, y, end=False, text_=None):
    e = rect(s, x, y, 0.9, 0.9, fill=WHITE, line=DARK if end else PURPLE, shape=MSO_SHAPE.OVAL, line_width=3.0 if end else 1.5)
    if text_:
        text(s, x - 1.0, y + 0.95, 2.9, 0.8, [text_], size=8, color=GREY, align=PP_ALIGN.CENTER)
    return e


def _gateway(s, x, y, text_=None):
    g = rect(s, x, y, 1.2, 1.2, fill=WHITE, line=PURPLE, shape=MSO_SHAPE.DIAMOND, line_width=1.5)
    label(g, ["×"], size=12, bold=True, color=PURPLE)
    if text_:
        text(s, x - 1.1, y - 0.75, 3.4, 0.8, [text_], size=8, color=GREY, align=PP_ALIGN.CENTER)
    return g


def slide_bpmn_incident(prs):
    s = new_slide(prs)
    header(s, "BPMN: от сигнала до решения")
    lanes = ["СМВУ и система", "Диспетчер", "Руководитель", "Бригада", "Аналитик"]
    X, Y, W, H = 1.0, 2.9, 31.8, 3.05
    _lanes(s, X, Y, W, lanes, H)
    row = lambda i, h=1.5: Y + i * H + (H - h) / 2  # noqa: E731
    start = _event(s, 4.6, row(0, 0.9), text_="сигнал датчика")
    norm = _task(s, 6.2, row(0), "Нормализация по профилю, эпизод")
    card_ = _task(s, 10.2, row(0), "Карточка: гипотезы, приоритет, чек-лист")
    notify = _task(s, 14.2, row(0), "Уведомление зоне (WebSocket)")
    ack = _task(s, 14.2, row(1), "Принять карточку («кто первый»)")
    g1 = _gateway(s, 18.4, row(1, 1.2), "принято в норматив?")
    esc = _task(s, 18.0, row(2), "Эскалация: перехват или назначение")
    check = _task(s, 20.4, row(1), "Проверка: история канала, камеры")
    decide = _task(s, 24.4, row(1), "Решение + «что произошло»")
    g2 = _gateway(s, 28.6, row(1, 1.2), "нужна работа?")
    draft = _task(s, 28.2, row(2), "Утвердить черновик заявки")
    work = _task(s, 28.2, row(3), "Работа, отчёт, состояние оборудования")
    end = _event(s, 31.3, row(1, 0.9) + 0.0, end=True)
    label_ = _task(s, 20.4, row(4), "Метка обучения: принять / отклонить")
    retrain = _task(s, 24.4, row(4), "Переобучение раз в неделю")
    for a, b, sa, sb in [
        (start, norm, "right", "left"), (norm, card_, "right", "left"), (card_, notify, "right", "left"),
        (notify, ack, "bottom", "top"), (ack, g1, "right", "left"), (g1, check, "right", "left"),
        (g1, esc, "bottom", "top"), (esc, check, "right", "bottom"), (check, decide, "right", "left"),
        (decide, g2, "right", "left"), (g2, draft, "bottom", "top"), (draft, work, "bottom", "top"),
        (g2, end, "right", "left"), (decide, label_, "bottom", "top"), (label_, retrain, "right", "left"),
    ]:
        arrow(s, a, b, sa, sb, width=1.25)
    text(s, 1.0, 18.2, 31.8, 0.8, ["Нормативы реакции: 5 / 15 / 60 / 240 мин по уровню; решение и причина из справочника "
                                  "сохраняются в журнале для анализа и дообучения (ТЗ §12)"], size=9, color=WHITE)


def slide_bpmn_maintenance(prs):
    s = new_slide(prs)
    header(s, "BPMN: процесс ТО")
    lanes = ["Система", "Инженер ТО", "Руководитель", "Бригада"]
    X, Y, W, H = 1.0, 3.0, 31.8, 3.6
    _lanes(s, X, Y, W, lanes, H)
    row = lambda i, h=1.5: Y + i * H + (H - h) / 2  # noqa: E731
    start = _event(s, 4.6, row(0, 0.9), text_="начало года")
    reg = _task(s, 6.2, row(0), "Реестр и регламент: ТО в год по видам")
    gen = _task(s, 10.2, row(0), "График ТО и ТР, план-график ППР")
    check = _task(s, 10.2, row(1), "Сверка с графиком заказчика, правки")
    approve = _task(s, 14.2, row(2), "Утвердить график")
    due = _task(s, 18.2, row(0), "Работы месяца + рекомендации по состоянию")
    plan = _task(s, 18.2, row(1), "«В план» на дату → черновик заявки")
    appr_wo = _task(s, 22.2, row(2), "Утвердить заявку, бригада зоны")
    do = _task(s, 22.2, row(3), "Выполнить, отчёт, состояние")
    g = _gateway(s, 26.6, row(3, 1.2), "требует ремонта?")
    rec = _task(s, 26.2, row(0), "Рекомендация: ремонт / замена")
    reg2 = _task(s, 29.0, row(1), "Дата ТО и состояние в реестр", w=3.2)
    end = _event(s, 31.4, row(3, 0.9), end=True)
    for a, b, sa, sb in [
        (start, reg, "right", "left"), (reg, gen, "right", "left"), (gen, check, "bottom", "top"),
        (check, approve, "right", "left"), (approve, due, "right", "bottom"), (due, plan, "bottom", "top"),
        (plan, appr_wo, "right", "left"), (appr_wo, do, "bottom", "top"), (do, g, "right", "left"),
        (g, rec, "top", "bottom"), (g, end, "right", "left"), (do, reg2, "top", "bottom"), (rec, plan, "left", "right"),
    ]:
        arrow(s, a, b, sa, sb, width=1.25)
    text(s, 1.0, 18.0, 31.8, 1.0, ["Регламент выведен из реальных графиков заказчика на 2026 год; ППР метановых датчиков: демонтаж → "
                                  "ОМ до 9:00 → вывоз → комиссия по рабочим дням"], size=9, color=WHITE)


def slide_ml(prs):
    s = new_slide(prs)
    header(s, "ML-конвейер")
    top = [
        ("Журналы СМВУ", "Kafka, CSV/XLSX, Parquet-архив 2019–2026"),
        ("Нормализация", "профили: пороги, служебные коды, аспекты"),
        ("Витрины", "сутки × канал, часы; Data Health"),
        ("Признаки на конец суток", "окна 1–90 суток, каскады объекта, погода"),
        ("LightGBM", "обучение 2019–2024 (без 2021)"),
    ]
    bottom = [
        ("Переобучение", "раз в неделю, чемпион / претендент, откат"),
        ("Метки из решений", "«что произошло» → правила → проверка аналитиком"),
        ("Журнал и исходы", "бэктест, реализованная точность"),
        ("Уровни риска", "пороги по точности на 2025 году"),
        ("Тест 2026", "отложенный год, сравнение с правилом"),
    ]
    tb, bb = [], []
    for i, (t, d) in enumerate(top):
        b = rect(s, 1.0 + i * 6.4, 3.3, 5.6, 3.0, fill=WHITE, radius=0.08)
        label(b, [(t, {"bold": True, "color": PURPLE, "size": 13}), (d, {"size": 10.5})])
        tb.append(b)
    for i, (t, d) in enumerate(bottom):
        b = rect(s, 1.0 + i * 6.4, 8.1, 5.6, 3.0, fill=PINK_LIGHT if i == 0 else WHITE, radius=0.08)
        label(b, [(t, {"bold": True, "color": PURPLE, "size": 13}), (d, {"size": 10.5})])
        bb.append(b)
    for a, b in zip(tb, tb[1:]):
        arrow(s, a, b, elbow=False, color=WHITE, width=2)
    arrow(s, tb[-1], bb[-1], "bottom", "top", elbow=False, color=WHITE, width=2)
    for a, b in zip(bb[::-1], bb[::-1][1:]):
        arrow(s, a, b, "left", "right", elbow=False, color=WHITE, width=2)
    arrow(s, bb[0], tb[0], "top", "bottom", elbow=False, color=PINK, width=2, dash=True)
    card(s, 1.0, 12.0, 15.6, 5.8, "Принципы", [
        "• Прогнозируется начало события: в выборке каналы «в норме» на конец суток",
        "• Одна функция признаков при обучении и в работе — расхождение проверено",
        "• Слабые метки из журналов: служебные коды, «1970», неисправности",
        "• Метрики только на отложенном годе; честное сравнение с простым правилом",
    ], size=11.5)
    card(s, 17.2, 12.0, 15.6, 5.8, "Пожар и НСД — без модели", [
        "• Подтверждённых событий нет: модель выучила бы ложные срабатывания",
        "• Индекс правил: подтверждения из разных датчиков с поправками",
        "• Вероятность — калибровка индекса по архиву: те же правила, шаг час, "
        "исход «угроза проявилась за 24 ч», монотонность (PAVA)",
        "• Пожар: Brier 0,249 против 0,296 для постоянной частоты",
    ], size=11.5)


def slide_results(prs):
    s = new_slide(prs)
    header(s, "Результаты: тест 2026 года")
    rows = [
        ["Задача", "ROC-AUC", "PR-AUC (случайная)", "Высокий: точность / полнота", "Правило: точность / полнота"],
        ["Отказ датчика, 24 ч", "0,90", "0,112 (0,006)", "0,21 / 0,09 · 32 в сутки", "0,10 / 0,45"],
        ["Метан ≥ 1 %, 24 ч", "0,94", "0,188 (0,004)", "0,08 / 0,74 · 20 в сутки", "0,07 / 0,39"],
        ["Подтопление, 24 ч", "0,82", "0,179 (0,040)", "0,15 / 0,46 · 21 в сутки", "0,13 / 0,54"],
    ]
    tbl = s.shapes.add_table(len(rows), len(rows[0]), Cm(1.0), Cm(3.3), Cm(31.8), Cm(5.2)).table
    widths = [7.0, 3.6, 5.6, 8.0, 7.6]
    for i, w in enumerate(widths):
        tbl.columns[i].width = Cm(w)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.text = val
            cell.fill.solid()
            cell.fill.fore_color.rgb = PURPLE if r == 0 else (WHITE if r % 2 else LANE)
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    _font(run, 11, r == 0, WHITE if r == 0 else INK)
    stats = [
        ("×33", "точнее случайного выбора: прогноз отказа уровня «высокий»"),
        ("74 %", "превышений метана ловит модель против 39 % у правила «был уровень ≥ 0,5 %»"),
        ("12 ч", "медианное упреждение прогноза отказа датчика"),
        ("×42", "сжатие потока: 90 250 сигналов → 2 138 карточек за 30 суток"),
    ]
    for i, (big, small) in enumerate(stats):
        x = 1.0 + i * 8.0
        rect(s, x, 9.3, 7.6, 4.2, fill=WHITE, radius=0.06)
        text(s, x + 0.4, 9.6, 6.8, 1.5, [big], size=28, bold=True, color=PINK)
        text(s, x + 0.4, 11.2, 6.8, 2.2, [small], size=11.5, color=INK)
    rect(s, 1.0, 14.2, 31.8, 3.6, fill=DARK, radius=0.06)
    text(s, 1.5, 14.5, 30.8, 3.1, [
        ("Честно о целях ТЗ", {"bold": True, "color": PINK, "size": 13}),
        ("«Точность > 0,7 и полнота > 0,5 одновременно» недостижимы: события — доли процента каналов в сутки, журналов "
         "ремонтов нет, метки слабые. Поэтому уровни риска выбраны по точности: «критический» — для немедленной реакции, "
         "«высокий» — для планирования проверки. Бэктест июня 2026: реализованная точность журнала 0,20 / 0,13 / 0,15.",
         {"color": WHITE}),
    ], size=11)


def slide_fire(prs):
    s = new_slide(prs)
    header(s, "Пожар и НСД, камеры")
    picture(s, IMG / "fire_probability.png", 1.2, 3.4, w=16.6)
    card(s, 18.6, 3.2, 14.2, 7.0, "Вероятность по истории", [
        "• Индекс правил посчитан по архиву 2019–2026 теми же правилами и окнами",
        "• Пожар: индекс 0,15–0,3 → 7 %, 0,3–0,75 → 42 %, от 0,75 → 63 %",
        "• В карточке: вероятность, индекс и число похожих случаев",
        "• НСД: повтор тревог 78 % почти при любом индексе — главное проверка",
    ], size=12.5)
    card(s, 18.6, 10.8, 14.2, 7.0, "Проверка по камерам (ТЗ §12, шаг 4)", [
        "• Ближайшие к месту тревоги камеры по пикетам",
        "• Кадр на момент тревоги из архива VMS и текущий кадр",
        "• Просмотр — в хронологии карточки и журнале действий",
        "• Адаптер VMS заказчика в .env, на стенде — эмулятор",
    ], size=12.5)


def slide_episode(prs):
    s = new_slide(prs)
    header(s, "Эпизод вместо сотни тревог")
    picture(s, IMG / "incident_cameras.png", 1.2, 3.4, w=18.4)
    card(s, 20.4, 3.2, 12.4, 14.6, "Что видит диспетчер", [
        "• Сколько сигналов и каналов склеено, первое и последнее событие",
        "• Гипотезы первопричины с весами: питание, связь, модуль датчика, работы, внешний фактор",
        "• Операционный приоритет 0–100: очередь по опасности, а не по времени",
        "• Чек-лист по типу инцидента и гипотезе",
        "• Кто уже смотрел карточку, кто первым откликнулся",
        "• Решение с ответом «что произошло» — метка для обучения",
        "• Черновик заявки одной кнопкой",
    ], size=12.5)


def slide_maintenance(prs):
    s = new_slide(prs)
    header(s, "Инженер ТО: графики")
    picture(s, IMG / "schedules.png", 1.2, 3.4, w=19.0)
    card(s, 21.0, 3.2, 11.8, 7.4, "Сверка с реальными графиками 2026", [
        "• Периодичность ТО совпала в 91 % строк",
        "• Число ТО+ТР в году — в 99 %",
        "• Пик нагрузки: 47 работ в месяц против 62",
        "• ППР: 15 партий против 16, конец 23.12 против 22.12",
    ], size=12.5)
    card(s, 21.0, 11.2, 11.8, 6.6, "Как это работает", [
        "• Регламент по видам оборудования из графика заказчика",
        "• Генератор выравнивает нагрузку по месяцам",
        "• XLSX в форме заказчика, утверждение — руководитель",
        "• Работы месяца → заявки → состояние от бригады",
    ], size=12.5)


def slide_constructor(prs):
    s = new_slide(prs)
    header(s, "Конструктор датчиков")
    layers = [("Сообщение", "JSON, CSV, строка контроллера, MQTT"), ("Шаблон формата", "где канал, время, значение, тревога"),
              ("Единое событие", "RawEvent — одно для всех источников"), ("Профиль датчика", "пороги, служебные коды, правила"),
              ("Конвейер", "нормализация, прогноз, карточки")]
    prev = None
    for i, (t, d) in enumerate(layers):
        b = rect(s, 1.0 + i * 6.4, 3.3, 5.6, 2.8, fill=PINK if i == 1 else WHITE, radius=0.1)
        label(b, [(t, {"bold": True, "size": 12, "color": WHITE if i == 1 else PURPLE}), (d, {"size": 9.5, "color": WHITE if i == 1 else INK})])
        if prev:
            arrow(s, prev, b, elbow=False, color=WHITE, width=2)
        prev = b
    picture(s, IMG / "constructor.png", 1.2, 7.1, w=14.6)
    rows = [["Что подключить", "Как", "Код"], ["Датчик нового формата", "шаблон + профиль", "не нужен"],
            ["Новый тип датчика", "профиль и правила", "не нужен"], ["Вид оборудования и регламент ТО", "запись регламента", "не нужен"],
            ["Система заказчика", "режим и адрес в .env", "не нужен"], ["Новая задача прогноза", "описание в specs.py", "немного"],
            ["Новый транспорт", "адаптер с тем же RawEvent", "немного"]]
    tbl = s.shapes.add_table(len(rows), 3, Cm(16.8), Cm(7.0), Cm(16.0), Cm(8.0)).table
    for i, w in enumerate((6.6, 6.0, 3.4)):
        tbl.columns[i].width = Cm(w)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.text = val
            cell.fill.solid()
            cell.fill.fore_color.rgb = PURPLE if r == 0 else (WHITE if r % 2 else LANE)
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    _font(run, 10, r == 0, WHITE if r == 0 else (PINK if c == 2 and val == "не нужен" else INK))
    text(s, 16.8, 15.6, 16.0, 2.4, ["Приём: HTTP от шлюза с ключом источника или обёртка в Kafka; песочница показывает разбор и нормализацию "
                                   "до подключения. Проверено: строка контроллера → Kafka → показание за секунды."], size=10, color=WHITE)


def slide_architecture(prs):
    s = new_slide(prs)
    header(s, "Архитектура и интеграции")
    col = [
        ("Источники", ["СМВУ → Kafka", "Файлы CSV/XLSX", "Шаблоны конструктора", "Open-Meteo"]),
        ("Ядро: модульный монолит Django", ["ingestion → normalization → telemetry", "forecasting → incidents → workorders",
                                              "accounts, topology (RBAC + зоны), audit", "integrations: адаптеры с режимами"]),
        ("Хранение", ["PostgreSQL 16 + TimescaleDB", "Parquet-архив 2019–2026", "Redis, Celery", "витрины сутки / часы"]),
        ("Клиенты и системы", ["React SPA + WebSocket", "REST API JSON/XML, OpenAPI", "help desk, реестр, VMS, AD", "Grafana, Prometheus"]),
    ]
    boxes = []
    for i, (t, items) in enumerate(col):
        x = 1.0 + i * 8.0
        b = rect(s, x, 3.3, 7.4, 7.6, fill=WHITE, radius=0.06)
        text(s, x + 0.4, 3.6, 6.6, 1.2, [t], size=12.5, bold=True, color=PURPLE)
        text(s, x + 0.4, 5.0, 6.6, 5.6, [f"• {it}" for it in items], size=10.5, color=INK)
        boxes.append(b)
    for a, b in zip(boxes, boxes[1:]):
        arrow(s, a, b, elbow=False, color=WHITE, width=2)
    card(s, 1.0, 11.6, 15.6, 6.2, "Системы заказчика", [
        "• Help desk: mock / rest / off, токен, пути, карта статусов",
        "• Реестр оборудования: API раз в сутки или файл CSV/XLSX",
        "• Видеонаблюдение: кадр на момент тревоги, ссылка на поток",
        "• AD по LDAPS: группа = роль, departmentNumber = зона",
        "• Страница «Интеграции»: режим, обмен, ошибка, проверка связи",
    ], size=12.5)
    card(s, 17.2, 11.6, 15.6, 6.2, "Контуры и развёртывание", [
        "• Оперативный контур, архив, витрины (ТЗ §13)",
        "• Учебный контур — подсистема на том же адресе",
        "• docker compose одной командой; закрытый контур — комплект образов",
        "• Только чтение из систем заказчика, кроме передачи заявки",
    ], size=12.5)


def slide_quality(prs):
    s = new_slide(prs)
    header(s, "Надёжность и безопасность")
    stats = [("47 мс", "медиана ответа при 20 одновременных пользователях"), ("≈5 с", "прогноз по всем объектам за цикл (ТЗ ≤ 300 с)"),
             ("242", "автотеста платформы и симулятора, линтеры, аудит зависимостей"), ("≤ 4 ч", "восстановление из ежедневной копии проверено")]
    for i, (big, small) in enumerate(stats):
        x = 1.0 + i * 8.0
        rect(s, x, 3.3, 7.6, 4.2, fill=WHITE, radius=0.06)
        text(s, x + 0.4, 3.6, 6.8, 1.5, [big], size=28, bold=True, color=PINK)
        text(s, x + 0.4, 5.2, 6.8, 2.2, [small], size=11.5, color=INK)
    card(s, 1.0, 8.2, 15.6, 9.6, "Безопасность (ТЗ §11)", [
        "• TLS 1.2+, HSTS, CSP, наружу только Caddy",
        "• RBAC: 8 ролей и зона ответственности на каждом запросе",
        "• LDAP/AD, блокировка подбора пароля, отзыв токенов",
        "• Журнал всех действий и просмотров карточек",
        "• Grafana: вход через систему, роль БД только на чтение",
        "• Отчёт о проверке и чек-лист ввода в эксплуатацию",
    ], size=12.5)
    card(s, 17.2, 8.2, 15.6, 9.6, "Эксплуатация", [
        "• Prometheus и Grafana: сервисы, очереди, задержка потока",
        "• Ежедневный pg_dump с ротацией 7 / 4 / 3",
        "• Инструкция по развёртыванию у заказчика, проверка check.sh",
        "• Документация 118 страниц и 8 руководств по ролям",
        "• 149-ФЗ и 152-ФЗ: только чтение, минимизация данных",
    ], size=12.5)


def slide_map(prs):
    s = new_slide(prs)
    header(s, "Карта мониторинга")
    picture(s, IMG / "monitoring_district.png", 1.2, 3.4, w=19.0)
    card(s, 21.0, 3.2, 11.8, 8.4, "Главный экран каждой роли", [
        "• Своя зона в цвете, смежные — пунктиром, чужие объекты — серым",
        "• Бейджи: число карточек и их уровень, заявки в работе и просроченные",
        "• Режимы: обстановка, прогноз, датчики, данные, заявки",
        "• Объект: датчики по пикетам, карточки, заявки",
    ], size=12.5)
    card(s, 21.0, 12.2, 11.8, 5.6, "В закрытом контуре", [
        "• Векторная карта OpenStreetMap, свой сервер тайлов",
        "• Без тайлов — пустой фон, зоны и бейджи работают",
    ], size=12.5)


def slide_mobile(prs):
    s = new_slide(prs)
    header(s, "Мобильное приложение в браузере")
    picture(s, IMG / "mobile_monitoring.png", 1.2, 3.4, h=14.2)
    picture(s, IMG / "guides" / "brigade_4_complete.png", 15.3, 3.4, h=14.2)
    card(s, 22.8, 3.2, 10.0, 8.2, "Без магазина приложений", [
        "• Открывается по ссылке в браузере телефона",
        "• «На главный экран» — значок и полноэкранный режим",
        "• Тот же вход, роли и зоны, что на ПК",
        "• Обновляется вместе с сервером",
    ], size=12.5)
    card(s, 22.8, 12.0, 10.0, 5.8, "На объекте", [
        "• Бригада: заявки на карте, «в работу», «выполнена», отчёт",
        "• Руководитель: утверждение с планшета",
        "• От 360 px, проверено на 25 страницах",
    ], size=12.5)


def slide_training(prs):
    s = new_slide(prs)
    header(s, "Учебный контур и учения")
    picture(s, IMG / "exercise.png", 1.2, 3.4, w=19.0)
    card(s, 21.0, 3.2, 11.8, 14.6, "Тренировка смены без риска", [
        "• Полигон из трёх объектов и симулятор датчиков: 9 сценариев",
        "• Учения: сценарий, темп, осложнение, «молчащий» участник",
        "• Разбор: отклик в норматив, решения, заявки, хронология",
        "• Учебные задания по ролям с подсказками и счётом ошибок",
        "• Вики: регламенты и памятки по ролям",
    ], size=12.5)


def slide_tz(prs):
    s = new_slide(prs)
    header(s, "Соответствие ТЗ")
    rows = [["Раздел", "Требование", "Реализация"],
            ["§3, §8", "Планирование ТО, черновики заявок", "Инженер ТО, план и графики ТО и ППР, рекомендации, заявки"],
            ["§4, §6", "Отказы, пожар, подтопление, НСД", "3 модели на 24 ч, индикаторы с вероятностью по истории"],
            ["§5", "Не заменяет диспетчера", "Решение и причина — за человеком, система предлагает"],
            ["§7", "CSV, XLSX, JSON, XML, GeoJSON, WKT", "Импорт, REST JSON/XML, схема в GeoJSON/WKT, конструктор"],
            ["§9, §11", "≤ 300 с, 20 пользователей", "≈5 с цикл прогноза, 47 мс при 20 пользователях"],
            ["§10", "Дашборд, карта, журнал, уведомления", "Мониторинг, оперативная обстановка, журнал прогнозов, WebSocket"],
            ["§11", "TLS, LDAP/AD, RBAC, журнал", "Caddy TLS, AD, 8 ролей и зоны, журнал действий и просмотров"],
            ["§12", "Пути «пожар» и «подтопление»", "Карточка → проверка по камерам → решение → метка для обучения"],
            ["§13", "Метео, только чтение, контуры", "Open-Meteo, адаптеры на чтение, оперативный контур, архив, витрины"],
            ["§14", "Документация, методы, библиотеки", "118 страниц, руководства по ролям, перечень библиотек, открытый код"]]
    tbl = s.shapes.add_table(len(rows), 3, Cm(1.0), Cm(3.2), Cm(31.8), Cm(14.6)).table
    for i, w in enumerate((3.2, 11.0, 17.6)):
        tbl.columns[i].width = Cm(w)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.text = val
            cell.fill.solid()
            cell.fill.fore_color.rgb = PURPLE if r == 0 else (WHITE if r % 2 else LANE)
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    _font(run, 10.5, r == 0 or c == 0, WHITE if r == 0 else INK)


def slide_business(prs):
    s = new_slide(prs)
    header(s, "Эффект для эксплуатации")
    items = [
        ("Меньше ложных выездов", "Карточка эпизода вместо сотни тревог (×42), гипотеза «потеря связи / питание», проверка по камерам до выезда"),
        ("Раньше о рисках", "Прогноз на 24 ч: метан ловится в 74 % случаев против 39 % у правила; упреждение отказа — 12 ч"),
        ("ТО по состоянию", "Рекомендации по прогнозам и осмотрам, ровная загрузка бригад: пик 47 работ против 62"),
        ("Прозрачная смена", "Нормативы реакции, эскалация, «кто первый», показатели сотрудников и отчёты PDF/XLSX"),
        ("Быстрое внедрение", "Одна команда развёртывания, закрытый контур, системы заказчика — режимом в .env"),
        ("Масштабирование", "Любые коллекторы и датчики — шаблоном и профилем; обучение смены на полигоне"),
    ]
    for i, (t, d) in enumerate(items):
        col, row = i % 3, i // 3
        x, y = 1.0 + col * 10.7, 3.3 + row * 7.3
        rect(s, x, y, 10.2, 6.8, fill=WHITE, radius=0.06)
        text(s, x + 0.5, y + 0.4, 9.2, 1.0, [f"0{i + 1}"], size=22, bold=True, color=PINK)
        text(s, x + 0.5, y + 1.8, 9.2, 1.0, [t], size=13, bold=True, color=PURPLE)
        text(s, x + 0.5, y + 2.9, 9.2, 3.8, [d], size=13, color=INK)


def slide_plans(prs):
    s = new_slide(prs)
    header(s, "Планы развития")
    stages = [("Пилот", ["AD и help desk заказчика", "поток СМВУ через шлюз", "реестр из учётной системы"]),
              ("Данные", ["режим охраны от шлюза для НСД", "журналы ремонтов → метки", "датчики уровня воды"]),
              ("Модели", ["прогноз на 7 суток для всех задач", "разбор ложных прогнозов", "контрфактические рекомендации"]),
              ("Продукт", ["офлайн-режим бригады", "учения по нескольким объектам", "тиражирование на другие районы"])]
    prev = None
    for i, (t, items) in enumerate(stages):
        x = 1.0 + i * 8.0
        b = rect(s, x, 3.4, 7.4, 1.8, fill=PINK if i == 0 else WHITE, radius=0.3)
        label(b, [t], size=14, bold=True, color=WHITE if i == 0 else PURPLE)
        if prev:
            arrow(s, prev, b, elbow=False, color=WHITE, width=2)
        prev = b
        rect(s, x, 5.8, 7.4, 8.4, fill=WHITE, radius=0.06)
        text(s, x + 0.4, 6.2, 6.6, 7.8, [f"• {it}" for it in items], size=13, color=INK)
    text(s, 1.0, 15.0, 31.8, 2.4, ["Каркас готов к развитию без переделки ядра: роли и зоны, журнал действий, отдельные контуры данных, "
                                  "общий конвейер моделей и конструктор источников."], size=12, color=WHITE)


def slide_final(prs):
    s = new_slide(prs, "Титульный слайд")
    text(s, 1.2, 6.0, 20.0, 2.5, ["Спасибо!"], size=44, bold=True, color=WHITE)
    text(s, 1.2, 9.0, 20.0, 5.0, [
        TEAM["name"],
        "Репозиторий: [ссылка]",
        "Прототип: [ссылка]",
        "Документация и руководства: [ссылка]",
    ], size=16, color=WHITE)


def build() -> Path:
    prs = Presentation(str(TEMPLATE))
    template_slides = list(prs.slides)
    fill_mandatory(prs)
    for fn in (slide_problem, slide_cycle, slide_features, slide_roles, slide_bpmn_incident, slide_bpmn_maintenance,
               slide_ml, slide_results, slide_map, slide_episode, slide_fire, slide_maintenance, slide_constructor,
               slide_architecture, slide_quality, slide_mobile, slide_training, slide_tz, slide_business, slide_plans, slide_final):
        fn(prs)
    # из шаблона остаются только обязательные 7–11, служебные и образцы удаляются
    for i, slide in enumerate(template_slides, start=1):
        if not 7 <= i <= 11:
            delete_slide(prs, slide)
    OUT.parent.mkdir(exist_ok=True)
    prs.save(str(OUT))
    return OUT


def to_pdf(path: Path) -> Path | None:
    try:
        import win32com.client
    except ImportError:
        return None
    pdf = path.with_suffix(".pdf")
    app = win32com.client.Dispatch("PowerPoint.Application")
    try:
        pres = app.Presentations.Open(str(path), WithWindow=False)
        pres.SaveAs(str(pdf), 32)
        pres.Close()
    finally:
        app.Quit()
    return pdf


if __name__ == "__main__":
    out = build()
    print(f"PPTX: {out}")
    pdf = to_pdf(out)
    if pdf:
        print(f"PDF:  {pdf}")
