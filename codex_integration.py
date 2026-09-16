"""Locate and modify the Codex config.toml to route through the gateway."""
import glob
import os
import re
import shutil
import time

PROVIDER_SECTION = "[model_providers.deepseek]"
GATEWAY_TOKEN = "sk-local-gateway"


def find_config_path():
    codex_home = os.environ.get("CODEX_HOME") or os.path.join(
        os.path.expanduser("~"), ".codex")
    return os.path.join(codex_home, "config.toml")


def status(config_path=None):
    path = config_path or find_config_path()
    result = {"exists": os.path.exists(path), "mode": "missing",
              "base_url": None, "backup": None}
    if not result["exists"]:
        return result
    text = _read(path)
    section = _provider_section(text)
    base_url = _section_value(section, "base_url")
    result["base_url"] = base_url
    if base_url and ("127.0.0.1" in base_url or "localhost" in base_url):
        result["mode"] = "gateway"
    else:
        result["mode"] = "direct"
    result["backup"] = _latest_backup(path)
    return result


def apply_gateway(config_path=None, port=8787):
    path = config_path or find_config_path()
    _backup(path)
    text = _read(path)
    if _provider_section(text) is None:
        text = _append_section(text, port)
    else:
        text = _rewrite_section(text, port)
    _write(path, text)
    return status(path)


def restore(config_path=None):
    path = config_path or find_config_path()
    backup = _latest_backup(path)
    if backup is None:
        return False
    _write(path, _read(backup))
    return True


def _backup(path):
    timestamp = time.strftime("%Y%m%d%H%M%S")
    backup_path = "{}.bak-gateway-{}".format(path, timestamp)
    if not os.path.exists(backup_path):
        shutil.copyfile(path, backup_path)


def _latest_backup(path):
    pattern = os.path.join(
        os.path.dirname(path), "config.toml.bak-gateway-*")
    matches = glob.glob(pattern)
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


def _provider_section(text):
    lines = text.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if line.strip() == PROVIDER_SECTION:
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].strip().startswith("["):
            end = index
            break
    return lines[start:end]


def _section_value(section_lines, key):
    if section_lines is None:
        return None
    pattern = re.compile(r"^{}\s*=\s*\"([^\"]*)\"".format(re.escape(key)))
    for line in section_lines:
        match = pattern.match(line.strip())
        if match:
            return match.group(1)
    return None


def _rewrite_section(text, port):
    lines = text.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if line.strip() == PROVIDER_SECTION:
            start = index
            break
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].strip().startswith("["):
            end = index
            break
    new_block = []
    replaced_url = False
    replaced_token = False
    for line in lines[start:end]:
        stripped = line.strip()
        if re.match(r"^base_url\s*=", stripped):
            new_block.append(
                'base_url = "http://127.0.0.1:{}/"\n'.format(port))
            replaced_url = True
        elif re.match(r"^experimental_bearer_token\s*=", stripped):
            new_block.append(
                'experimental_bearer_token = "{}"\n'.format(GATEWAY_TOKEN))
            replaced_token = True
        else:
            new_block.append(line)
    if not replaced_url:
        new_block.insert(
            1, 'base_url = "http://127.0.0.1:{}/"\n'.format(port))
    if not replaced_token:
        _insert_token_after_base_url(new_block)
    return ("".join(lines[:start]) + "".join(new_block)
            + "".join(lines[end:]))


def _insert_token_after_base_url(new_block):
    for index, line in enumerate(new_block):
        if line.strip().startswith("base_url"):
            new_block.insert(
                index + 1,
                'experimental_bearer_token = "{}"\n'.format(GATEWAY_TOKEN))
            return


def _append_section(text, port):
    block = (
        "\n" + PROVIDER_SECTION + "\n"
        'name = "deepseek"\n'
        'base_url = "http://127.0.0.1:{}/"\n'.format(port)
        + 'wire_api = "responses"\n'
        + 'experimental_bearer_token = "{}"\n'.format(GATEWAY_TOKEN)
    )
    if not text.endswith("\n"):
        text += "\n"
    return text + block


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
