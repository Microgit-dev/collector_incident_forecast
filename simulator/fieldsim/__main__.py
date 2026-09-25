"""
Консоль симулятора.

    python -m fieldsim serve                         движок + веб-интерфейс (http://localhost:8095)
    python -m fieldsim run fire 900100 --speed 10    сценарий без сервера, до завершения
    python -m fieldsim tree | list 900101 | set 90000001 alarm | scenario fire 900100 | runs | log
                                                     управление запущенным симулятором (--server)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request

from .vocab import MODES

DEFAULT_SERVER = os.environ.get("SIM_SERVER", "http://localhost:8095")


def _engine(args, announce: bool):
    from .catalog import Catalog
    from .engine import Engine
    from .sinks import make_sink

    catalog = Catalog.load(args.catalog)
    sink = make_sink(args.sink, args.bootstrap, args.topic)
    engine = Engine(catalog, sink)
    logging.info(
        "catalog: %d objects, %d channels; sink: %s", len(catalog.objects), len(catalog.devices), sink.status()
    )
    if announce:
        logging.info("announced %d messages", engine.announce())
    return engine


def cmd_serve(args):
    from .web import serve

    engine = _engine(args, not args.no_announce)
    engine.start()
    if args.commands:
        from .commands import start_listener

        start_listener(engine, args.bootstrap, args.commands)
    try:
        serve(engine, args.host, args.port, args.contour)
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()


def cmd_run(args):
    engine = _engine(args, args.announce)
    run = engine.start_scenario(args.scenario, args.object, args.picket, args.speed)
    for step in run.steps:
        print(f"  · {step.title}")
    engine.start()
    try:
        engine.wait_runs()
    except KeyboardInterrupt:
        engine.stop_run(run.id)
    engine.stop()
    print(f"готово: отправлено {engine.sent} сообщений; {engine.sink.status()}")


# ---------- управление запущенным симулятором ----------


def _call(args, method: str, path: str, body: dict | None = None):
    request = urllib.request.Request(
        args.server.rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = json.loads(exc.read() or b"{}").get("detail", exc.reason)
        sys.exit(f"ошибка: {detail}")
    except urllib.error.URLError as exc:
        sys.exit(f"симулятор недоступен по {args.server}: {exc.reason}")


def _action(args, **body):
    result = _call(args, "POST", "/api/action", body)
    print("ok" if result.get("ok") else result)


def cmd_tree(args):
    def walk(nodes, depth=0):
        for node in nodes:
            print(f"{'  ' * depth}{node['id']:>8}  {node['name']}  ({node['channels']} кан.)")
            walk(node["children"], depth + 1)

    walk(_call(args, "GET", "/api/meta")["tree"])


def cmd_list(args):
    state = _call(args, "GET", f"/api/state?object={args.object}")
    for ch in state["channels"]:
        value = f"{ch['value']:g}" if ch["value"] is not None else ""
        op = {True: "вкл", False: "выкл", None: ""}[ch["op"]]
        name, kind = ch["name"][:34], ch["type"][:22]
        print(f"{ch['id']:>10}  {name:<34} {kind:<22} {ch['mode_title']:<12} {value:>6} {op:<4} {ch['last_raw'][:28]}")
    for zone in state["guard"]:
        print(f"охрана: {zone['name']} — {'на охране' if zone['on'] else 'снята'}")


def cmd_runs(args):
    for run in _call(args, "GET", "/api/state")["runs"]:
        progress = f"{run['done']}/{run['total']}"
        print(f"#{run['id']} {run['title']} · {run['object']} · ×{run['speed']:g} · {progress} · {run['status']}")
        for line in run["log"]:
            print(f"     {line}")
        if run["next"]:
            print(f"     далее: {run['next']}")


def cmd_log(args):
    for item in reversed(_call(args, "GET", "/api/state")["log"][: args.n]):
        if "error" in item:
            print(f"{item['ts'][11:19]}  ОШИБКА {item['error']}")
            continue
        flag = "!" if item["alarm"] else " "
        print(f"{item['ts'][11:19]} {flag} {item['channel']:>10}  {item['name'][:34]:<34} {item['raw']}")


def cmd_scenarios(args):
    for s in _call(args, "GET", "/api/meta")["scenarios"]:
        print(f"{s['code']:<11} {s['title']:<18} {s['description']}")


def cmd_scenario(args):
    body = {"scenario": args.scenario, "object": args.object, "picket": args.picket, "speed": args.speed}
    result = _call(args, "POST", "/api/scenario", body)
    print(f"запуск #{result['id']}:")
    for title in result["steps"]:
        print(f"  · {title}")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="fieldsim", description="Симулятор датчиков СМВУ")
    parser.add_argument("--catalog", default=os.environ.get("SIM_CATALOG", "polygon"), help="каталог со справочниками")
    parser.add_argument("--sink", default=os.environ.get("SIM_SINK", "stdout"), help="kafka | stdout | file:путь")
    parser.add_argument("--bootstrap", default=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    parser.add_argument("--topic", default=os.environ.get("KAFKA_TOPIC", "smvu.training-events"))
    parser.add_argument("--server", default=DEFAULT_SERVER, help="адрес запущенного симулятора")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="движок и веб-интерфейс")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8095)
    p.add_argument("--contour", default=os.environ.get("SIM_CONTOUR", "учебный контур"))
    p.add_argument("--no-announce", action="store_true", help="не отправлять начальное состояние каналов")
    p.add_argument(
        "--commands",
        default=os.environ.get("SIM_COMMANDS_TOPIC", ""),
        help="тема Kafka с командами учебного контура (восстановить объект, запустить сценарий)",
    )
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("run", help="сценарий без сервера, до завершения")
    p.add_argument("scenario")
    p.add_argument("object", type=int)
    p.add_argument("--picket", type=float)
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--announce", action="store_true")
    p.set_defaults(func=cmd_run)

    sub.add_parser("tree", help="дерево объектов").set_defaults(func=cmd_tree)
    p = sub.add_parser("list", help="каналы объекта и их состояние")
    p.add_argument("object", type=int)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("set", help=f"режим канала: {', '.join(MODES)}")
    p.add_argument("channel", type=int)
    p.add_argument("mode", choices=list(MODES))
    p.set_defaults(func=lambda a: _action(a, op="mode", channel=a.channel, mode=a.mode))

    p = sub.add_parser("value", help="показание числового датчика")
    p.add_argument("channel", type=int)
    p.add_argument("value", type=float)
    p.set_defaults(func=lambda a: _action(a, op="value", channel=a.channel, value=a.value))

    p = sub.add_parser("ramp", help="плавно довести показание до цели")
    p.add_argument("channel", type=int)
    p.add_argument("target", type=float)
    p.add_argument("--seconds", type=float, default=120)
    p.set_defaults(func=lambda a: _action(a, op="ramp", channel=a.channel, target=a.target, seconds=a.seconds))

    p = sub.add_parser("op", help="включить / выключить насос, вентилятор")
    p.add_argument("channel", type=int)
    p.add_argument("state", choices=["on", "off"])
    p.set_defaults(func=lambda a: _action(a, op="op", channel=a.channel, on=a.state == "on"))

    p = sub.add_parser("guard", help="поставить объект на охрану / снять")
    p.add_argument("object", type=int)
    p.add_argument("state", choices=["on", "off"])
    p.set_defaults(func=lambda a: _action(a, op="guard", object=a.object, on=a.state == "on"))

    p = sub.add_parser("raw", help="произвольное сырое значение")
    p.add_argument("channel", type=int)
    p.add_argument("raw")
    p.add_argument("--alarm", choices=["true", "false"])
    p.set_defaults(func=lambda a: _action(a, op="raw", channel=a.channel, raw=a.raw, alarm=a.alarm))

    p = sub.add_parser("sentinel", help="служебный код производителя (−100)")
    p.add_argument("channel", type=int)
    p.set_defaults(func=lambda a: _action(a, op="sentinel", channel=a.channel))

    p = sub.add_parser("cascade", help="все каналы объекта разом в режим")
    p.add_argument("object", type=int)
    p.add_argument("mode", choices=list(MODES))
    p.set_defaults(func=lambda a: _action(a, op="cascade", object=a.object, mode=a.mode))

    p = sub.add_parser("flap", help="дребезг: неисправность и восстановление")
    p.add_argument("channel", type=int)
    p.add_argument("--times", type=int, default=4)
    p.add_argument("--period", type=float, default=20)
    p.set_defaults(func=lambda a: _action(a, op="flap", channel=a.channel, times=a.times, period=a.period))

    p = sub.add_parser("restore", help="всё под объектом (или везде) в норму")
    p.add_argument("object", type=int, nargs="?")
    p.set_defaults(func=lambda a: _action(a, op="restore", object=a.object))

    sub.add_parser("scenarios", help="доступные сценарии").set_defaults(func=cmd_scenarios)
    p = sub.add_parser("scenario", help="запустить сценарий на работающем симуляторе")
    p.add_argument("scenario")
    p.add_argument("object", type=int)
    p.add_argument("--picket", type=float)
    p.add_argument("--speed", type=float, default=1.0)
    p.set_defaults(func=cmd_scenario)

    sub.add_parser("runs", help="запуски сценариев").set_defaults(func=cmd_runs)
    p = sub.add_parser("stop", help="остановить запуск")
    p.add_argument("run", type=int)
    p.set_defaults(func=lambda a: print(_call(a, "POST", f"/api/scenario/{a.run}/stop", {})))
    p = sub.add_parser("log", help="последние отправленные сообщения")
    p.add_argument("-n", type=int, default=30)
    p.set_defaults(func=cmd_log)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
