import os
import sys

import argparse
import itertools
import json
import subprocess

from datetime import datetime
from pathlib import Path
from string import Template

import pandas as pd
import matplotlib.pyplot as plt

# This tool requires key-authorized SSH access to all hosts
# - the SSH daemon must be running on each designated host
# - runner host on must be pre-authorized on each host
#   (no password or key acknowledgment prompts are supported)


DEFAULT_RECEIVER_PORT = 12000
DEFAULT_SENDER_PORT = 12001

command = Template('"$set_env saturate -n $name -d $dir $command $post_args"')
proc_recv = None
proc_send = None


def run(conf: dict, dir: str):
    global proc_recv
    global proc_send

    try:
        _run(conf, dir)
        gen(conf, dir)
    except Exception as exc:  # noqa
        for proc in [proc_send, proc_recv]:
            if not proc:
                continue
            proc.kill()
            proc.wait()
        raise exc


def _run(conf: dict, dir: str):
    global proc_recv
    global proc_send

    host_pairs = conf["hosts"]
    time = int(conf["time"])
    env_keys = sorted(conf["env"].keys())

    for n, host_pair in enumerate(host_pairs):
        recv_port = None
        send_port = None

        if "ports" in conf and len(conf["ports"]) > n:
            recv_port, send_port = conf["ports"][n]

        if not recv_port:
            recv_port = DEFAULT_RECEIVER_PORT
        if not send_port:
            send_port = DEFAULT_SENDER_PORT

        for items in itertools.product(*[conf["env"][key] for key in env_keys]):
            test_name = "_".join(
                ["-".join(host_pair), *[str(i).replace("://", "_") for i in items]]
            )
            env = {name: items[i] for i, name in enumerate(env_keys)}

            print(f"Running ({time}s)")
            print(f"  name:\t {test_name}")
            print(f"  env:\t {env}")
            print("")

            print(f"  spawning receiver")
            env["YA_NET_BIND_URL"] = f"udp://0.0.0.0:{recv_port}"
            proc_recv, node, csv = _spawn_receiver(test_name, host_pair[0], env, time)

            print(f"  spawning sender -> {node}")
            env["YA_NET_BIND_URL"] = f"udp://0.0.0.0:{send_port}"
            proc_send = _spawn_sender(test_name, host_pair[1], env, time, node)

            print("   waiting ...")
            exit_codes = [p.wait() for p in (proc_recv, proc_send)]
            if any(c != 0 for c in exit_codes):
                raise RuntimeError("Failure: exit code != 0")

            print("   downloading results ...")
            proc = subprocess.Popen(
                f"scp {host_pair[0]}:{csv} {dir}",
                stdout=subprocess.DEVNULL,
                shell=True,
            )
            proc.communicate(timeout=5)
            print("")

        print("DONE.")


def _spawn_receiver(test_name: str, host: str, env: dict, time: int):
    time += 2

    now = _now_str()
    cmd = command.safe_substitute(
        set_env=_env_cmd(env),
        name=f"'{test_name}_recv'",
        dir=f"'/tmp/ya-relay-saturate-{now}'",
        command="listen",
        post_args=f"-s {time}s",
    )
    ssh_cmd = f"ssh {host} {cmd}"

    node_s = "node:"
    node, csv = None, None
    proc = subprocess.Popen(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)

    for line in proc.stdout:
        line = line.decode("utf-8").replace("\t", "").strip()

        node_idx = line.find(node_s)
        if node_idx != -1:
            node = line[node_idx + len(node_s) :].strip()

        if line.startswith("csv:"):
            csv = line.replace("csv:", "").strip()
            break

    if not node:
        raise RuntimeError("Failure: no node id")
    if not csv:
        raise RuntimeError("Failure: no CSV file")

    return proc, node, csv


def _spawn_sender(test_name, host, env, time, node):
    now = _now_str()
    cmd = command.safe_substitute(
        set_env=_env_cmd(env),
        name=f"'{test_name}_send'",
        dir=f"'/tmp/ya-relay-saturate-{now}'",
        command="connect",
        post_args=f"{node} -t {time}s",
    )
    ssh_cmd = f"ssh {host} {cmd}"

    return subprocess.Popen(ssh_cmd, stdout=subprocess.DEVNULL, shell=True)


def plot(name: str, files: list, indexes: dict, dir: str):
    headers = ["time", "node", "Bps", "B total"]
    dir = Path(dir)
    path = f"{Path(dir) / name}.png"

    for file in files:
        df = pd.read_csv(file, names=headers)
        idx = df["Bps"].idxmax()
        node = df.iloc[idx]["node"]
        res_df = df.loc[df["node"] == node]

        plt.plot(res_df["time"], res_df["Bps"], label=label(file, indexes))

    plt.legend(loc="best", fontsize="x-small")
    plt.xlabel("test time [s]", fontsize="x-small")
    plt.ylabel("B/s", fontsize="x-small")
    plt.yscale("log")

    plt.grid(visible=True, which="major", color="gray", linestyle="dashed")
    plt.grid(visible=True, which="minor", color="r", linestyle="dotted")

    print(f"Saving plot: {path}")

    plt.savefig(path, dpi=200)
    plt.close()


def label(file_name: Path, indexes: dict):
    split = file_name.stem.split("_")

    if indexes["rx"] == -1:
        rx = "?"
    else:
        rx = split[indexes["rx"] + 2]

    if indexes["tx"] == -1:
        tx = "?"
    else:
        tx = split[indexes["tx"] + 2]

    return f"rx {rx}, tx {tx}"


def category(file_name: Path):
    split = file_name.stem.split("_")
    return "_".join(split[0:3])


def gen(conf, dir: str):
    files = [Path(dir) / f for f in os.listdir(dir) if f.endswith(".csv")]
    categorized = {}

    env_keys = sorted(conf["env"].keys())
    indexes = {}

    try:
        indexes["rx"] = env_keys.index("YA_NET_TCP_MAX_RECV_BUF_SIZE")
    except:  # noqa
        indexes["rx"] = -1
    try:
        indexes["tx"] = env_keys.index("YA_NET_TCP_MAX_SEND_BUF_SIZE")
    except:  # noqa
        indexes["tx"] = -1

    for file in files:
        cat = category(file)
        if cat not in categorized:
            categorized[cat] = []
        categorized[cat].append(file)

    for cat, files in categorized.items():
        plot(cat, sorted(files), indexes, dir)


def _run_args(args):
    conf = _prep_args(args)
    run(conf, args.dir)


def _gen_args(args):
    conf = _prep_args(args)
    gen(conf, args.dir)


def _prep_args(args):
    os.makedirs(args.dir, exist_ok=True)
    with open(args.conf, "r") as f:
        return json.load(f)


def _env_cmd(env):
    return " ".join([f"export {name}='{val}' ;" for name, val in env.items()])


def _now_str():
    return datetime.now().strftime("%H_%M_%S_%f")[:-3]


def main(args):
    parser = argparse.ArgumentParser(description="Saturate test runner")
    parser.add_argument("conf", type=str, help="configuration JSON file")
    parser.add_argument("dir", type=str, help="data directory")

    subparsers = parser.add_subparsers(help="command to execute")

    parser_run = subparsers.add_parser("run", help="run tests")
    parser_run.set_defaults(func=_run_args)

    parser_gen = subparsers.add_parser("gen", help="plot data from csv files")
    parser_gen.set_defaults(func=_gen_args)

    args = parser.parse_args(args)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
