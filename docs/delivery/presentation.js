// Презентация решения (ТЗ §15): node docs/delivery/presentation.js <каталог node_modules>
// Скриншоты — docs/delivery/img, цифры — те же, что в сопроводительной документации.
const path = require("path");
const modules = process.argv[2] || path.join(__dirname, "node_modules");
// resolve с paths учитывает поле exports пакетов
const req = (m) => require(require.resolve(m, { paths: [path.dirname(modules)] }));
const pptxgen = req("pptxgenjs");
const sharp = req("sharp");
const fs = require("fs");
// Иконки Tabler (MIT) — SVG из зависимостей интерфейса, тот же набор, что в самом приложении
const ICONS = path.join(__dirname, "..", "..", "frontend", "node_modules", "@tabler", "icons", "icons", "outline");

const IMG = path.join(__dirname, "img");
const OUT = path.join(__dirname, "out", "Презентация.pptx");

const C = {
  ink: "15222B", // глубокий графит — фон титула и финала
  slate: "243642",
  text: "1D2A33",
  muted: "5B6B76",
  line: "D5DEE4",
  paper: "FFFFFF",
  mist: "EEF3F6",
  signal: "E8772E", // сигнальный оранжевый — риск, тревога
  calm: "1F9E8F", // бирюзовый — норма, результат
  sky: "8FC1E3",
};
const HEAD = "Calibri";
const BODY = "Calibri";

async function icon(name, color, size = 256) {
  const svg = fs
    .readFileSync(path.join(ICONS, `${name}.svg`), "utf8")
    .replace(/currentColor/g, `#${color}`)
    .replace(/width="24"/, `width="${size}"`)
    .replace(/height="24"/, `height="${size}"`);
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + png.toString("base64");
}

async function main() {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE"; // 13.33 × 7.5
  pres.title = "Прогноз инцидентов инженерных коллекторов";
  const W = 13.33;

  const ic = {};
  for (const [name, file, color] of [
    ["bolt", "bolt", C.paper],
    ["layers", "stack-2", C.paper],
    ["alert", "alert-triangle", C.paper],
    ["check", "checks", C.paper],
    ["brain", "brain", C.paper],
    ["flame", "flame", C.paper],
    ["gas", "cloud-fog", C.paper],
    ["drop", "droplet", C.paper],
    ["door", "door-enter", C.paper],
    ["sensor", "antenna-bars-5", C.paper],
    ["users", "users-group", C.paper],
    ["clip", "clipboard-list", C.paper],
    ["chart", "chart-bar", C.paper],
    ["shield", "shield-lock", C.paper],
    ["clock", "clock-hour-4", C.paper],
    ["db", "database", C.paper],
    ["route", "route", C.paper],
    ["school", "school", C.paper],
    ["history", "history", C.paper],
    ["target", "target", C.paper],
  ]) {
    ic[name] = await icon(file, color);
  }

  // Иконка в круге — сквозной мотив
  const badge = (slide, x, y, d, key, fill) => {
    slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { color: fill } });
    const pad = d * 0.22;
    slide.addImage({ data: ic[key], x: x + pad, y: y + pad, w: d - 2 * pad, h: d - 2 * pad });
  };
  const title = (slide, text, sub) => {
    slide.addText(text, {
      x: 0.6, y: 0.35, w: W - 1.2, h: 0.8, fontFace: HEAD, fontSize: 32, bold: true, color: C.text, margin: 0, isTextBox: true,
    });
    if (sub) {
      slide.addText(sub, {
        x: 0.6, y: 1.1, w: W - 1.2, h: 0.45, fontFace: BODY, fontSize: 15, color: C.muted, margin: 0, isTextBox: true,
      });
    }
  };
  const shot = (slide, file, x, y, w) => {
    const h = w * (1350 / 2160);
    slide.addImage({
      path: path.join(IMG, file), x, y, w, h,
      shadow: { type: "outer", color: "000000", opacity: 0.18, blur: 8, offset: 3, angle: 90 },
    });
    return h;
  };
  const card = (slide, x, y, w, h, fill = C.mist) =>
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: fill }, rectRadius: 0.08 });
  const text = (slide, t, o) => slide.addText(t, { fontFace: BODY, color: C.text, margin: 0, isTextBox: true, valign: "top", ...o });

  // 1. Титул
  {
    const s = pres.addSlide();
    s.background = { color: C.ink };
    badge(s, 0.8, 0.9, 1.0, "sensor", C.signal);
    text(s, "Прогноз инцидентов\nинженерных коллекторов", { x: 0.8, y: 2.1, w: 8.5, h: 1.9, fontFace: HEAD, fontSize: 44, bold: true, color: C.paper });
    text(s, "Отказы датчиков, пожар, загазованность, подтопление и несанкционированный доступ — до того, как они случились", {
      x: 0.8, y: 4.15, w: 7.8, h: 0.9, fontSize: 18, color: C.sky,
    });
    text(s, "Задача «8. ДЖКХ» · АО «Москоллектор»", { x: 0.8, y: 6.4, w: 6, h: 0.4, fontSize: 14, color: "9FB2BF" });
    const stats = [
      ["×42", "сигналов сжимается\nв карточки"],
      ["33×", "точнее случайного —\nпрогноз отказа датчика"],
      ["21 ч", "упреждение в демо-\nсценарии отказа"],
    ];
    stats.forEach(([big, small], i) => {
      const y = 1.3 + i * 1.75;
      text(s, big, { x: 9.5, y, w: 3.3, h: 0.9, fontFace: HEAD, fontSize: 48, bold: true, color: i === 0 ? C.signal : C.paper });
      text(s, small, { x: 9.5, y: y + 0.85, w: 3.3, h: 0.7, fontSize: 13, color: "9FB2BF" });
    });
    s.addNotes("Сервис предиктивной аналитики для диспетчеров Москоллектора. Три цифры: поток сигналов сжимается в 42 раза, прогноз отказа датчика в 33 раза точнее случайного, в демо-сценарии отказ предсказан за 21 час.");
  }

  // 2. Проблема
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "Тысячи сигналов в сутки, а отказы — без предупреждения", "Что показали 14 ГБ журналов СМВУ за 2019–2026 годы");
    const facts = [
      ["3 000", "сигналов в сутки — переходы каналов в тревогу и сбой", C.signal, "bolt"],
      ["11 485", "каналов на 95 объектах: дым, газ, вода, доступ, насосы, питание", C.slate, "sensor"],
      ["0,6 %", "каналов в сутки начинают отказывать — событие редкое", C.slate, "target"],
      ["0", "подтверждённых пожаров и проникновений: тревоги в основном ложные", C.slate, "flame"],
    ];
    facts.forEach(([big, small, color, key], i) => {
      const x = 0.6 + i * 3.08;
      card(s, x, 2.0, 2.85, 3.6);
      badge(s, x + 0.3, 2.3, 0.75, key, color);
      text(s, big, { x: x + 0.3, y: 3.25, w: 2.4, h: 0.9, fontFace: HEAD, fontSize: 40, bold: true, color });
      text(s, small, { x: x + 0.3, y: 4.2, w: 2.3, h: 1.2, fontSize: 14, color: C.muted });
    });
    text(s, "Журналов ремонтов, решений диспетчеров и реестра оборудования в выгрузке нет — метки отказа слабые, и система должна учиться на решениях самих диспетчеров.", {
      x: 0.6, y: 6.0, w: 12.1, h: 0.8, fontSize: 15, italic: true, color: C.muted,
    });
    s.addNotes("Проблема: поток около 3000 сигналов в сутки, редкие события отказа, отсутствие подтверждённых пожаров и НСД, нет журналов ремонтов.");
  }

  // 3. Идея
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "От сигнала к решению — и обратно в модель", "Система предлагает, человек решает, его решение учит систему");
    const steps = [
      ["bolt", "Сигнал", "Поток СМВУ через Kafka, единая нормализация любых датчиков", C.slate],
      ["layers", "Эпизод", "Сотни сигналов объекта склеиваются в одну карточку", C.slate],
      ["alert", "Риск и приоритет", "Гипотезы причины, приоритет 0–100, прогноз на 24 ч", C.signal],
      ["check", "Решение", "Что произошло, причина, заявка бригаде; эскалация по таймауту", C.slate],
      ["brain", "Обучение", "Решение → метка → переобучение под контролем аналитика", C.calm],
    ];
    steps.forEach(([key, head, body, color], i) => {
      const x = 0.6 + i * 2.5;
      badge(s, x + 0.65, 2.1, 1.0, key, color);
      if (i < steps.length - 1) {
        s.addShape(pres.shapes.LINE, { x: x + 1.8, y: 2.6, w: 1.3, h: 0, line: { color: C.line, width: 2, endArrowType: "triangle" } });
      }
      text(s, head, { x, y: 3.35, w: 2.3, h: 0.5, fontSize: 18, bold: true, align: "center" });
      text(s, body, { x, y: 3.9, w: 2.3, h: 1.4, fontSize: 13, color: C.muted, align: "center" });
    });
    card(s, 0.6, 5.6, 12.1, 1.1);
    text(s, "Сервис не заменяет диспетчера и не управляет оборудованием (ТЗ §5): он показывает риск, его причины и следующее действие.", {
      x: 0.9, y: 5.85, w: 11.5, h: 0.6, fontSize: 15, color: C.text,
    });
    s.addNotes("Главная идея — замкнутый цикл: сигнал, эпизод, риск, решение человека, обучение модели на этом решении.");
  }

  // 4. Главный экран
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "Главный экран: 472 сигнала → 6 карточек", "Поток, эпизоды и очередь «требуют действия» — на одном экране, по приоритету");
    shot(s, "dashboard.png", 0.6, 1.75, 8.4);
    const points = [
      ["Сырые сигналы", "переходы в тревогу и сбой за 10 мин, 1 ч или сутки"],
      ["Эпизоды", "склейка по объекту и контуру риска; сжатие потока видно сразу"],
      ["Требуют действия", "не взятые карточки, просрочка реакции, эскалации"],
      ["Активные риски", "пять задач прогноза: каналы критического, высокого и среднего уровня"],
    ];
    points.forEach(([head, body], i) => {
      const y = 1.85 + i * 1.28;
      badge(s, 9.35, y, 0.5, ["bolt", "layers", "alert", "target"][i], i === 2 ? C.signal : C.slate);
      text(s, head, { x: 10.0, y: y - 0.02, w: 2.8, h: 0.4, fontSize: 15, bold: true });
      text(s, body, { x: 10.0, y: y + 0.38, w: 2.8, h: 0.8, fontSize: 12, color: C.muted });
    });
    s.addNotes("Главный экран после демо-сценариев: 472 сигнала за 10 минут стали 6 карточками. Очередь отсортирована по операционному приоритету.");
  }

  // 5. Сжатие потока
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "Поток тревог сжимается в 42 раза", "30 суток данных заказчика, та же склейка, что в работе");
    text(s, "90 250", { x: 0.6, y: 2.0, w: 4, h: 1.1, fontFace: HEAD, fontSize: 60, bold: true, color: C.slate });
    text(s, "сигналов потока\n≈ 3 008 в сутки", { x: 0.6, y: 3.1, w: 4, h: 0.8, fontSize: 15, color: C.muted });
    text(s, "→", { x: 4.2, y: 2.05, w: 0.8, h: 1.0, fontSize: 48, color: C.line });
    text(s, "2 138", { x: 5.0, y: 2.0, w: 3.6, h: 1.1, fontFace: HEAD, fontSize: 60, bold: true, color: C.calm });
    text(s, "карточек-эпизодов\n≈ 71 в сутки", { x: 5.0, y: 3.1, w: 3.6, h: 0.8, fontSize: 15, color: C.muted });
    card(s, 9.0, 1.9, 3.7, 2.2, C.ink);
    text(s, "×42", { x: 9.3, y: 2.1, w: 3.2, h: 1.2, fontFace: HEAD, fontSize: 66, bold: true, color: C.signal });
    text(s, "меньше решений на смену", { x: 9.3, y: 3.35, w: 3.2, h: 0.5, fontSize: 14, color: C.paper });
    const rows = [
      ["Потеря связи на «Кси», 24.06.2026", "270 сигналов по 127 каналам → 1 карточка «потеря связи»"],
      ["«Каппа ПС», 17.06.2024", "2 078 сигналов → 2 карточки; 7 из 8 каналов из топа прогноза отказали в тот же день"],
      ["Гипотезы причины", "питание, связь, модуль, отдельный датчик, работы на объекте, ложное срабатывание — с весами и доказательствами"],
    ];
    rows.forEach(([head, body], i) => {
      const y = 4.6 + i * 0.75;
      text(s, head, { x: 0.6, y, w: 4.2, h: 0.6, fontSize: 14, bold: true });
      text(s, body, { x: 4.9, y, w: 7.8, h: 0.6, fontSize: 14, color: C.muted });
    });
    s.addNotes("Сигналы склеиваются по объекту и контуру риска, пока пауза не больше 30 минут. За 30 суток 90 тысяч сигналов стали 2 тысячами карточек.");
  }

  // 6. Пять рисков
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "Пять рисков: три модели и два индикатора", "Горизонт 24 часа (отказ датчика — также 7 суток); тест — отложенный 2026 год");
    const risks = [
      ["sensor", "Отказ датчика", "LightGBM, 33 признака", "точность 0,21\nполнота 0,09\nупреждение 12 ч", C.slate],
      ["gas", "Загазованность", "LightGBM, метан ≥ 1 %", "ловит 74 %\nпревышений\n(правило — 39 %)", C.slate],
      ["drop", "Подтопление", "LightGBM + погода", "точность 0,15\nполнота 0,45\nнасосы АНС", C.slate],
      ["flame", "Пожар", "индикатор по правилам", "дым, тепло,\nрост температуры,\nсоседние извещатели", C.signal],
      ["door", "НСД", "индикатор по правилам", "контакт и движение,\nрежим охраны, ночь;\nнаряд снижает риск", C.signal],
    ];
    risks.forEach(([key, head, method, result, color], i) => {
      const x = 0.6 + i * 2.46;
      card(s, x, 1.95, 2.3, 4.2);
      badge(s, x + 0.25, 2.2, 0.8, key, color);
      text(s, head, { x: x + 0.25, y: 3.15, w: 1.9, h: 0.45, fontSize: 17, bold: true });
      text(s, method, { x: x + 0.25, y: 3.6, w: 1.9, h: 0.7, fontSize: 12, color: C.muted });
      text(s, result, { x: x + 0.25, y: 4.45, w: 1.95, h: 1.4, fontSize: 13, color: C.text });
    });
    text(s, "Для пожара и НСД подтверждённых событий в данных нет: модель научилась бы предсказывать ложные срабатывания. Поэтому — объяснимый индекс по правилам и формулировка «риск», а не «факт».", {
      x: 0.6, y: 6.35, w: 12.1, h: 0.7, fontSize: 13, italic: true, color: C.muted,
    });
    s.addNotes("Три модели на едином конвейере признаков и два индикатора по правилам. Для каждого — метрики на отложенном 2026 годе.");
  }

  // 7. Карточка прогноза
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "Каждый прогноз объясним", "Почему риск высокий, насколько ему верить и что делать");
    shot(s, "forecast_card.png", 4.3, 1.75, 8.4);
    const items = [
      ["Факторы", "вклад каждого признака (SHAP): «65 суток с неисправностями из 90»"],
      ["Насколько доверять", "точность уровня на тесте, итог журнала, сравнение с правилом"],
      ["Качество данных", "Data Health канала: полнота, свежесть, стабильность"],
      ["Что делать", "чек-лист и черновик заявки из рекомендации по ТО"],
    ];
    items.forEach(([head, body], i) => {
      const y = 1.85 + i * 1.3;
      text(s, head, { x: 0.6, y, w: 3.4, h: 0.4, fontSize: 16, bold: true, color: i === 0 ? C.signal : C.text });
      text(s, body, { x: 0.6, y: y + 0.42, w: 3.4, h: 0.8, fontSize: 13, color: C.muted });
    });
    s.addNotes("Карточка прогноза: критический риск 72 % по каналу насосной станции. Отказ случился через 21 час — это третий демо-сценарий.");
  }

  // 8. Достоверность — нативный график
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "Проверено на реальных данных, а не на выдуманных", "Обучение 2019–2024, пороги — 2025, отложенный тест — 2026; бэктест июня 2026 года");
    s.addChart(pres.charts.BAR, [{ name: "Во сколько раз точнее случайного", labels: ["Подтопление", "Загазованность", "Отказ датчика"], values: [3.8, 20, 33] }], {
      x: 0.6, y: 1.8, w: 6.2, h: 4.6, barDir: "bar",
      showTitle: true, title: "Прогноз «высокий»: во сколько раз точнее случайного", titleFontSize: 14, titleColor: C.text, titleFontFace: BODY,
      chartColors: [C.signal], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: 'General"×"', dataLabelFontSize: 13, dataLabelColor: C.text,
      catAxisLabelColor: C.text, catAxisLabelFontSize: 13, valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" },
      showLegend: false,
    });
    const rows = [
      ["Бэктест июня: реализованная точность", "0,20 · 0,13 · 0,15", "отказ · газ · подтопление"],
      ["Полнота по факту: предупреждено событий", "18 % · 93 % · 43 %", "104/569 · 52/56 · 36/84"],
      ["Признаки в обучении и в работе", "0 расхождений", "проверено по всем задачам"],
      ["Цель ТЗ P > 0,7 и R > 0,5", "недостижима", "события редки, метки слабые — уровни выбраны по точности"],
    ];
    rows.forEach(([head, big, small], i) => {
      const y = 1.9 + i * 1.15;
      card(s, 7.2, y, 5.5, 1.0);
      text(s, head, { x: 7.45, y: y + 0.12, w: 5.1, h: 0.35, fontSize: 13, color: C.muted });
      text(s, big, { x: 7.45, y: y + 0.45, w: 2.6, h: 0.45, fontSize: 18, bold: true, color: i === 3 ? C.signal : C.text });
      text(s, small, { x: 10.1, y: y + 0.5, w: 2.5, h: 0.45, fontSize: 11, color: C.muted });
    });
    s.addNotes("Метрики честные: цель ТЗ одновременно по точности и полноте на этих данных недостижима, уровни риска выбраны по точности и прозрачно показаны.");
  }

  // 9. Командная вертикаль
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "Командная вертикаль и эскалация", "Карточка не потеряется: если её никто не взял — она поднимается выше");
    const levels = [
      ["Руководство района", "утверждает заявки, видит эскалации и аналитику"],
      ["ОДС района", "дежурные смены; весь район"],
      ["Диспетчерская объекта", "первой получает карточки своего объекта"],
      ["Бригада", "исполняет заявки, отчёт — обратно в карточку"],
    ];
    levels.forEach(([head, body], i) => {
      const y = 1.9 + i * 1.2;
      const x = 0.6 + i * 0.45;
      card(s, x, y, 5.6, 0.95, i === 2 ? "FCE9DC" : C.mist);
      text(s, head, { x: x + 0.3, y: y + 0.12, w: 5.1, h: 0.4, fontSize: 16, bold: true });
      text(s, body, { x: x + 0.3, y: y + 0.52, w: 5.1, h: 0.35, fontSize: 12, color: C.muted });
    });
    badge(s, 8.1, 1.95, 0.8, "clock", C.signal);
    text(s, "5 мин", { x: 9.1, y: 1.95, w: 3.5, h: 0.6, fontFace: HEAD, fontSize: 32, bold: true, color: C.signal });
    text(s, "на реакцию по критической карточке, 15 мин — по высокой; дальше эскалация", { x: 9.1, y: 2.6, w: 3.6, h: 0.8, fontSize: 13, color: C.muted });
    badge(s, 8.1, 3.75, 0.8, "users", C.slate);
    text(s, "7 ролей · зоны", { x: 9.1, y: 3.75, w: 3.6, h: 0.6, fontFace: HEAD, fontSize: 26, bold: true });
    text(s, "видно только своё поддерево объектов; вход через LDAP/AD", { x: 9.1, y: 4.35, w: 3.6, h: 0.8, fontSize: 13, color: C.muted });
    badge(s, 8.1, 5.5, 0.8, "check", C.calm);
    text(s, "Закрепление", { x: 9.1, y: 5.5, w: 3.6, h: 0.6, fontFace: HEAD, fontSize: 26, bold: true });
    text(s, "взявший карточку работает с ней один; видно, кто её уже смотрел", { x: 9.1, y: 6.1, w: 3.6, h: 0.8, fontSize: 13, color: C.muted });
    s.addNotes("Вертикаль: бригада, диспетчерская объекта, ОДС, руководство. Эскалация по таймауту реакции, закрепление карточки, журнал просмотров.");
  }

  // 10. Схема
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "Схема коллекторов по пикетам", "Координат у заказчика нет — трассы строятся по пикетам каналов (GeoJSON / WKT)");
    shot(s, "scheme.png", 0.6, 1.75, 8.4);
    const items = [
      ["Цвет участка", "максимальный риск каналов участка по любой задаче"],
      ["Точки", "каналы не в норме и молчащие каналы"],
      ["Треугольники", "открытые карточки; пунктир — прогнозные"],
      ["Щелчок", "подробности участка: каналы, Data Health, риск по задачам"],
    ];
    items.forEach(([head, body], i) => {
      const y = 1.85 + i * 1.28;
      text(s, head, { x: 9.35, y, w: 3.4, h: 0.4, fontSize: 16, bold: true });
      text(s, body, { x: 9.35, y: y + 0.42, w: 3.4, h: 0.8, fontSize: 13, color: C.muted });
    });
    s.addNotes("Схема: 16 трасс, около 60 участков на трассу, цвет — риск, отметки — сбои, молчание и карточки.");
  }

  // 11. Обратная связь
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "Решения диспетчеров учат модель", "«Что произошло» становится меткой; аналитик видит каждую и может её отменить");
    shot(s, "learning.png", 4.3, 1.75, 8.4);
    const causes = [
      ["Неисправность датчика", "подтверждает отказ", C.calm],
      ["Потеря связи, обесточивание", "«неисправен» — не отказ", C.signal],
      ["Работы на объекте", "исключить из обучения", C.slate],
      ["Отказ предотвращён по прогнозу", "не считается ошибкой модели", C.slate],
    ];
    causes.forEach(([head, effect, color], i) => {
      const y = 1.85 + i * 1.28;
      s.addShape(pres.shapes.OVAL, { x: 0.6, y: y + 0.08, w: 0.22, h: 0.22, fill: { color }, line: { color } });
      text(s, head, { x: 1.0, y, w: 3.1, h: 0.4, fontSize: 15, bold: true });
      text(s, effect, { x: 1.0, y: y + 0.42, w: 3.1, h: 0.6, fontSize: 13, color: C.muted });
    });
    text(s, "Новая версия заменяет модель, только если лучше на той же валидации.", { x: 0.6, y: 6.55, w: 3.4, h: 0.6, fontSize: 12, italic: true, color: C.muted });
    s.addNotes("Правила разметки настраивает аналитик. Каждая метка видна, её можно отклонить. Переобучение раз в неделю по схеме чемпион-претендент, контроль деградации.");
  }

  // 12. Заявки и ТО
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "От прогноза к работам: рекомендации и заявки", "Рекомендация → черновик → утверждение → система учёта заявок → бригада → отчёт");
    const flow = ["Рекомендация", "Черновик", "Утверждена", "Принята", "Бригада", "В работе", "Выполнена", "Закрыта"];
    flow.forEach((step, i) => {
      const x = 0.6 + i * 1.53;
      const ours = i < 3;
      card(s, x, 2.0, 1.38, 0.8, ours ? C.slate : C.calm);
      text(s, step, { x, y: 2.0, w: 1.38, h: 0.8, fontSize: 13, bold: true, color: C.paper, align: "center", valign: "middle" });
    });
    text(s, "в системе прогнозирования", { x: 0.6, y: 2.9, w: 4.4, h: 0.35, fontSize: 12, color: C.muted });
    text(s, "в системе учёта заявок заказчика (статусы — только чтение)", { x: 5.2, y: 2.9, w: 7.4, h: 0.35, fontSize: 12, color: C.muted });
    const facts = [
      ["483", "рекомендации по ТО: прогнозы, Data Health, просрочки ТО по реестру"],
      ["1 минута", "синхронизация статусов, бригады и отчёта исполнителя"],
      ["Хронология", "передача, начало работ и итог — в карточке инцидента"],
    ];
    facts.forEach(([big, small], i) => {
      const x = 0.6 + i * 4.1;
      card(s, x, 3.7, 3.8, 2.4);
      badge(s, x + 0.3, 3.95, 0.7, "clip", i === 0 ? C.signal : C.slate);
      text(s, big, { x: x + 0.3, y: 4.8, w: 3.3, h: 0.6, fontFace: HEAD, fontSize: 26, bold: true });
      text(s, small, { x: x + 0.3, y: 5.4, w: 3.3, h: 0.7, fontSize: 13, color: C.muted });
    });
    s.addNotes("Заявка проходит путь от рекомендации до закрытия; в стенде система учёта заявок заказчика заменена эмулятором с полным жизненным циклом.");
  }

  // 13. Аналитика
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "Аналитика для руководства", "Эффективность смен, качество прогнозов, отчёты PDF и XLSX, дашборд Grafana");
    shot(s, "analytics.png", 0.6, 1.75, 8.4);
    const kpis = [
      ["5,3 мин", "до просмотра карточки (медиана)"],
      ["25 мин", "до решения (медиана)"],
      ["6 %", "эскалаций по таймауту"],
      ["PDF · XLSX", "отчёт за период и журналы"],
    ];
    kpis.forEach(([big, small], i) => {
      const y = 1.85 + i * 1.28;
      text(s, big, { x: 9.35, y, w: 3.4, h: 0.6, fontFace: HEAD, fontSize: 28, bold: true, color: i < 3 ? C.calm : C.text });
      text(s, small, { x: 9.35, y: y + 0.6, w: 3.4, h: 0.5, fontSize: 13, color: C.muted });
    });
    text(s, "Цифры — по эмуляции смен на реальных эпизодах июня 2026: она помечена и в обучение не попадает.", {
      x: 9.35, y: 6.45, w: 3.4, h: 0.7, fontSize: 11, italic: true, color: C.muted,
    });
    s.addNotes("Истории работы диспетчеров в выгрузке нет, поэтому метрики показаны на эмуляции смен, помеченной и исключаемой одним переключателем.");
  }

  // 14. Архитектура
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "Архитектура: модульный монолит, одна команда запуска", "docker compose up — 19 сервисов, без внешних платных зависимостей");
    const cols = [
      ["Источники", ["СМВУ → Kafka", "CSV / XLSX журналов", "LDAP / AD", "Open-Meteo", "Система учёта заявок"], C.slate],
      ["Ядро (Django + DRF)", ["Нормализация и хранение", "Эпизоды, гипотезы, приоритет", "Модели LightGBM и индикаторы", "Роли, зоны, эскалация", "Заявки, аналитика, аудит"], C.signal],
      ["Хранение", ["TimescaleDB: оперативный контур", "Parquet: архив журналов", "Суточные витрины", "Redis: задачи и кеш"], C.slate],
      ["Клиенты", ["React SPA + WebSocket", "REST API: JSON, XML", "Админка Django", "Grafana, Prometheus"], C.calm],
    ];
    cols.forEach(([head, items, color], i) => {
      const x = 0.6 + i * 3.1;
      card(s, x, 1.9, 2.85, 4.5);
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.2, y: 2.1, w: 2.45, h: 0.6, fill: { color }, line: { color }, rectRadius: 0.06 });
      text(s, head, { x: x + 0.2, y: 2.1, w: 2.45, h: 0.6, fontSize: 14, bold: true, color: C.paper, align: "center", valign: "middle" });
      text(
        s,
        items.map((t, j) => ({ text: t, options: { bullet: true, breakLine: j < items.length - 1 } })),
        { x: x + 0.25, y: 2.95, w: 2.45, h: 3.3, fontSize: 13, paraSpaceAfter: 8 },
      );
      if (i < cols.length - 1) {
        s.addShape(pres.shapes.LINE, { x: x + 2.87, y: 4.15, w: 0.2, h: 0, line: { color: C.muted, width: 2, endArrowType: "triangle" } });
      }
    });
    text(s, "Python 3.12 · Django 5.2 · Celery · Kafka 3.9 · PostgreSQL 16 + TimescaleDB · LightGBM · Polars · React 19 · TypeScript · Mantine · Caddy (TLS)", {
      x: 0.6, y: 6.65, w: 12.1, h: 0.45, fontSize: 13, color: C.muted, align: "center",
    });
    s.addNotes("Модульный монолит: модули с явными границами, любой можно вынести в сервис. Новый источник — адаптер, новый тип датчика — профиль нормализации в админке.");
  }

  // 15. Нефункциональные
  {
    const s = pres.addSlide();
    s.background = { color: C.ink };
    text(s, "Нефункциональные требования — с замерами", { x: 0.6, y: 0.4, w: 12, h: 0.8, fontFace: HEAD, fontSize: 32, bold: true, color: C.paper });
    const stats = [
      ["≈ 5 с", "прогноз по всем объектам\n(ТЗ: ≤ 300 с на объект)", "clock"],
      ["47 мс", "медиана ответа\nпри 20 пользователях", "users"],
      ["14 с", "восстановление БД из копии\n(ТЗ: ≤ 4 часов)", "db"],
      ["TLS · LDAP · RBAC", "журнал действий и просмотров,\n149-ФЗ и 152-ФЗ", "shield"],
    ];
    stats.forEach(([big, small, key], i) => {
      const x = 0.6 + i * 3.1;
      badge(s, x, 1.9, 0.9, key, i === 3 ? C.calm : C.signal);
      text(s, big, { x, y: 3.1, w: 2.95, h: 0.9, fontFace: HEAD, fontSize: i === 3 ? 26 : 44, bold: true, color: C.paper, valign: "bottom" });
      text(s, small, { x, y: 4.15, w: 2.9, h: 1.0, fontSize: 14, color: "9FB2BF" });
    });
    text(s, "106 автотестов · ruff и oxlint · перечень библиотек с лицензиями · открытый исходный код без обфускации", {
      x: 0.6, y: 6.2, w: 12.1, h: 0.5, fontSize: 15, color: C.sky,
    });
    s.addNotes("Все цифры замерены на стенде: 4 ядра, 8 ГБ памяти. Нагрузочный скрипт и процедура восстановления описаны в документации.");
  }

  // 16. Демо-сценарии
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "Три демо-сценария на настоящих эпизодах", "Эпизод из архива подаётся в систему как живой поток — всё остальное работает как в эксплуатации");
    const demos = [
      ["layers", "Поток тревог", "«Кси», 24.06.2026", "Сотни переходов в «не определено» → одна карточка «потеря связи» с гипотезой и чек-листом", C.slate, "demo_scenario alarms"],
      ["flame", "Пожарный риск", "«Кси ПК202–ПК302», 29.06.2026", "Дымовые извещатели подтверждают друг друга → критическая карточка, приоритет 100, эскалация через 5 мин", C.signal, "demo_scenario fire"],
      ["sensor", "Отказ датчика", "«ДУ объект Альфа», 01–02.06.2026", "Критический прогноз 72 % → через 21 час канал отказал → решение → метка → заявка", C.calm, "demo_scenario sensor"],
    ];
    demos.forEach(([key, head, where, body, color, cmd], i) => {
      const x = 0.6 + i * 4.1;
      card(s, x, 1.95, 3.8, 4.0);
      badge(s, x + 0.3, 2.2, 0.9, key, color);
      text(s, head, { x: x + 0.3, y: 3.3, w: 3.3, h: 0.5, fontSize: 20, bold: true });
      text(s, where, { x: x + 0.3, y: 3.8, w: 3.3, h: 0.4, fontSize: 13, color: C.muted });
      text(s, body, { x: x + 0.3, y: 4.3, w: 3.3, h: 1.5, fontSize: 14 });
      text(s, cmd, { x: x + 0.3, y: 5.4, w: 3.3, h: 0.4, fontSize: 12, fontFace: "Courier New", color: C.muted });
    });
    s.addNotes("Демонстрация: команда demo_scenario публикует эпизод в Kafka с текущим временем; перед этим каналы приводятся в состояние на начало эпизода.");
  }

  // 17. Ограничения и развитие
  {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    title(s, "Честно об ограничениях — и что дальше", "");
    const limits = [
      "Метка отказа — неисправность в журнале СМВУ: журналов ремонтов нет",
      "Пожар и НСД — индикаторы: подтверждённых событий в данных нет",
      "Погода для подтопления дала прирост в пределах шума",
      "Системы заказчика (help desk, AD, реестр) в стенде эмулированы",
    ];
    const next = [
      ["school", "Режим обучения по ролям на учебном полигоне"],
      ["history", "Просмотр исторических показаний за период"],
      ["route", "Учения: настраиваемые сценарии для всей цепочки"],
      ["chart", "Отчётность и метрики сотрудников"],
    ];
    card(s, 0.6, 1.4, 5.9, 5.3);
    text(s, "Ограничения", { x: 0.9, y: 1.6, w: 5.3, h: 0.5, fontSize: 20, bold: true, color: C.signal });
    text(s, limits.map((t, j) => ({ text: t, options: { bullet: true, breakLine: j < limits.length - 1 } })), {
      x: 0.9, y: 2.25, w: 5.3, h: 4.2, fontSize: 15, paraSpaceAfter: 14,
    });
    text(s, "Развитие после сдачи", { x: 6.9, y: 1.6, w: 5.8, h: 0.5, fontSize: 20, bold: true, color: C.calm });
    next.forEach(([key, t], i) => {
      const y = 2.3 + i * 1.1;
      badge(s, 6.9, y, 0.7, key, C.slate);
      text(s, t, { x: 7.8, y: y + 0.12, w: 4.9, h: 0.6, fontSize: 15 });
    });
    text(s, "Каркас уже готов: роли, журнал действий, разбор эпизодов, отдельный контур данных.", { x: 6.9, y: 6.7, w: 5.8, h: 0.4, fontSize: 12, italic: true, color: C.muted });
    s.addNotes("Ограничения следуют из данных, а не из архитектуры: при появлении журналов ремонтов и подтверждённых событий модели переобучаются на том же конвейере.");
  }

  // 18. Финал
  {
    const s = pres.addSlide();
    s.background = { color: C.ink };
    badge(s, 0.8, 1.0, 1.0, "check", C.calm);
    text(s, "Готово к проверке", { x: 0.8, y: 2.3, w: 11, h: 1.0, fontFace: HEAD, fontSize: 44, bold: true, color: C.paper });
    const items = [
      "Исходный код — открытый, с автотестами и инструкцией по сборке",
      "Прототип — разворачивается одной командой docker compose up",
      "Сопроводительная документация — DOCX и PDF",
      "Три демо-сценария на данных заказчика — по одной команде",
    ];
    text(s, items.map((t, j) => ({ text: t, options: { bullet: true, breakLine: j < items.length - 1 } })), {
      x: 0.8, y: 3.5, w: 11.5, h: 2.6, fontSize: 18, color: C.paper, paraSpaceAfter: 12,
    });
    text(s, "Сервис прогнозирования инцидентов инженерных коллекторов · АО «Москоллектор»", { x: 0.8, y: 6.6, w: 11, h: 0.4, fontSize: 13, color: "9FB2BF" });
  }

  await pres.writeFile({ fileName: OUT });
  console.log("written", OUT);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
