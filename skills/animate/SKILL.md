---
name: animate
description: Drive Adobe Animate from Claude via JSFL scripts — open .fla, inspect symbols/layers/frames/pivots, move/rotate parts, add Rotation keyframes, render symbol frames to PNG to look at them, save. Use for MLP puppet (.fla) work when the user asks to edit/inspect/render in Animate.
---

# Animate через JSFL

Claude не рисует мышкой. Всё делается скриптами JSFL, которые запускает `run_jsfl.py`.

## Запуск

```
python C:/Users/user/.claude/skills/animate/run_jsfl.py <script.jsfl> [--timeout 300]
```

- Раннер ищет `Animate.exe` в `C:/Program Files/Adobe/Adobe Animate*/`; переопределить: env `ANIMATE_EXE`.
- Скрипт оборачивается: подключается `lib.jsfl`, ошибки ловятся, всё из `log()` печатается в stdout.
- Диалоги Animate отвечает сторож `dialogs.py`: он встроен в раннер, а для долгих сессий есть `python dialogs.py --watch --log файл`. Правила: «долго выполняется» — Нет, «выполнить как команду» — Выполнить, «восстановить» — Нет, «сохранить изменения» — Нет. Неизвестные окна только пишутся в лог. Обёртка ставит `fl.showIdleMessage(false)`.
- Лог пишется построчно: при краше видно последнюю выполненную строку.
- Animate открывает окно (headless нет). Если уже запущен — скрипт уходит в открытый экземпляр.
- Скрипты пиши в scratchpad, не в папки с ассетами.

## lib.jsfl (доступно в скрипте)

- `log(x)` — вывод (объекты → JSON).
- `uri(path)` — путь Windows → `file:///C|/...`.
- `openDoc(path)` → document. `saveAs(doc, path)` — сохранить КОПИЮ.
- `listSymbols(doc, filter)` — имена символов библиотеки.
- `describeSymbol(doc, name)` — слои, лейблы, ключевые кадры, элементы (имя символа, матрица, пивот).
- `renderSymbol(doc, name, f0, f1, outDir)` — PNG-секвенция кадров символа (1-based) → смотреть через Read.
- `setTransform(doc, sym, layer, frame, idx, {a,b,c,d,tx,ty})`, `setPivot(..., x, y)`.
- Рисование:
  - `openCopy(src, dst)` — копия файла и открыть её (имя dst каждый раз новое: открытый файл не перезаписать);
  - `editAt(doc, sym, layer, frame)` — войти в символ (слой по имени создаётся);
  - `style(doc, stroke, width, fill)`;
  - `drawPath(doc, [["M",x,y],["C",...],["Q",...],["L",...],["Z"]], smooth)` — кривые раскладываются на отрезки, потом `optimizeCurves`;
  - `clearLayer(doc)`, `selectLayer(doc)` — ТОЛЬКО текущий слой (`doc.selectAll` берёт все слои — не использовать);
  - `recolor(doc, sym, frame, {"#OLD":"#NEW"})` — перекрасить заливки (через `contour.fill =`, работает без краша);
  - `readShapes(...)` — контуры кадра (квадратичные Безье); `exitEdit(doc)`.
- НЕ РАБОТАЕТ:
  - `warp()` (vertex.setLocation / edge.setControl в beginEdit) — КРАШИТ Animate 2024; деформировать через `xfl.py warp`;
  - `drawSVG` (`importFile`) — ничего не импортирует;
  - `path.addCurve` теряет контрольные точки.

- `makeView(doc, sym, base, other, N, t, {символ: кадр})` — новый ракурс в кадре N: копия ключа base по всем слоям, части сдвинуты на долю t к ключу other (тот же слой и символ), внутренние кадры частей подменяются по словарю (значение-массив — по порядку встреч). Пары кадров N, N+1.
- `renderLayers(doc, sym, frame, outDir, layers|null)` — каждый слой кадра (0-based) отдельным PNG `<NN>_<слой>.png` + `bounds.json` (части в общих координатах; для сравнения с масками из 3D).
- Animate 2024: `exportToPNGSequence(f, f)` пишет ДВА кадра (f и f+1), имена 1-based.

## Геометрия без JSFL: xfl.py (Python + numpy)

Правка вектора прямо в XML внутри .fla. Точно (round-trip пиксель в пиксель проверен) и без крашей API вершин.
- `xfl.py unpack <fla> <dir>` / `pack <dir> <fla>` (mimetype первым). Файл не должен быть открыт в Animate при pack.
- `xfl.py symbols <dir> [filter]`, `xfl.py layers <dir> <symbol> [--frame N]` — слои, ключи, экземпляры (`имя:firstFrame`).
- `xfl.py compare <dir> <symbol> 101,107,111` — таблица слой × кадр (`символ:firstFrame`): сразу видно, какие внутренние кадры частей меняются между ракурсами и какие нарисованы, но не используются.
- `xfl.py export <dir> <symbol> --frame N [--layer L] -o shapes.json` — фигуры кадра: заливки/обводки (цвет или сырой xml), рёбра как `[["M",x,y],["L",x,y],["Q",cx,cy,x,y]]` в px символа, `sid` фигуры.
- `xfl.py import <dir> shapes.json` — записать обратно (по `sid`; `sid: null` + `layer` + `frame` — новая фигура в ключ).
- `xfl.py warp <dir> <symbol> --frame N --pts pts.json [--layer L] [--no-instances] [--deep N] [--bend]` — TPS по опорным точкам `{"src":[[x,y]..],"dst":[[x,y]..]}`. Экземпляры — аффинно по якобиану поля; фигуры — каждая своим регуляризованным аффинным приближением (+ матрицы градиентов; фигуры со своей `<matrix>` — в их координатах). `--bend` гнёт фигуры внутри (кривые бьются на куски, при самопересечении — откат на аффинное). `--deep N` — вложенные символы копируются (`Имя__w<run>_<n>`) и гнутся внутри.
  - ОСТОРОЖНО: `--deep`/`--bend` на DHX-символах ненадёжны — Animate молча выкидывает часть фигур (тонкие каёмки, радужки с градиентом). Надёжно: деталь целиком (`--deep 0`) или команда Animate ниже.
  - `pack` ждёт до 30 с, если Animate ещё держит только что закрытый .fla.
- Цикл: unpack → правка → pack в НОВОЕ имя → Animate `renderSymbol`/`renderLayers` → `look.py diff/onion` → повтор.

## Поворот части «как кружку»: part3d.py + команда Animate

- Модель пони — облако точек по частям: Blender `luna3d.py dump` (PONY=имя) → `G:/mlp_characters/mlp_2d/tools/turn3d/data/model_<пони>.json` (есть Луна, Селестия).
- `part3d.py field --model M --part head,horn,crown --from A --to B --box l,t,r,b [--damp 0.8 --reg 3000] -o pts.json` — поле сдвигов при повороте на B−A (общий сдвиг части вычитается — его делает сборка поворота). `--shape ellipsoid [--depth k]` — гладкий эллипсоид по рамке без складок (без модели). Рамка — у головы по основе головы/ушам/рогу.
- `part3d.py fit --pts pts.json --elements els.json -o out.json` — аффинное на каждую деталь по её рамке (устойчивее якобиана в точке).
- `part3d.py apply file.fla symbol --frame N --pts pts.json [--deep 0]` — unpack → warp → pack.
- Команда для пользователя: `commands/Повернуть часть по 3D.jsfl` (установлена в `%LOCALAPPDATA%/Adobe/Animate 2024/ru_RU/Configuration/Commands`). Выделить экземпляр → Команды → ввести градусы. Копирует символ (`Имя__turnN`), двигает детали внутри копии; файл не закрывается, Ctrl+Z работает. Автотест: угол в `Configuration/part3d_auto.txt` вместо окна. Лог: `Configuration/part3d_log.txt`.
- Проверено на голове Луны: ±5.6/11.25° от анфаса — рог прямой, глаза/чёлка целы, дальняя сторона сжимается.

## Глаза: look.py (Python314, PIL)

Каждая команда пишет PNG (по умолчанию в `C:/Temp/claude/animate_look/`); смотреть его через Read.

- `look.py screen` — скриншот окна Animate (`--full` — весь экран). Смотреть, когда что-то зависло: там может быть диалог или ошибка.
- `look.py grid <png> --step 20` — рендер с сеткой в координатах символа (красные линии — оси 0). Помогает задать точки для `drawPath`.
- `look.py onion a.png b.png [...]` — наложение: первый красным, последний синим, средние как есть. Это калька для промежуточного ракурса.
- `look.py diff <a.png> <ref.png>` — силуэт против эталона в координатах символа: IoU, % лишнего (красное) и недостающего (синее), диапазон расхождений.
- `look.py sheet <png...>`, `look.py zoom <png> x0 y0 x1 y1 --k 4` — лист кадров и увеличенный кусок (координаты символа).
- `grid`, `onion` и `zoom` берут координаты символа из `bounds.json`, который пишет `renderSymbol`. Вся серия кадров лежит на общем холсте.

## Правила

- Перед правкой — копия `.fla` (`saveAs` в новый файл). Оригиналы DHX в `G:/mlp_characters/mlp_2d/official` не перезаписывать.
- CS4-бинарные .fla (начинаются с `D0 CF`) Animate открывает; после `saveAs` они становятся CC/XFL и читаются нашим экспортёром.
- Рисовать можно (`drawPath`), но точки кривых Claude задаёт вслепую. Каждый рисунок надо рендерить (`renderSymbol`), смотреть через Read и поправлять. Цвета берутся из палитры персонажа (`readShapes` / `contours[].fill.color`).
- Деформацию существующих фигур через API вершин не делать (краш). Вместо этого `xfl.py export/import/warp`.
- Без Animate: `.fla` CC = zip с XFL; читать/править XML можно напрямую (`G:/mlp_characters/mlp_2d/tools`, xfl2svg).
- Animate ставит и логинит пользователь (аккаунт Adobe), Claude не устанавливает.
