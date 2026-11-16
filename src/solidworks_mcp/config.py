"""Runtime configuration: env vars, config.local.json, path sandboxing."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .errors import InvalidParameterError, PathNotAllowedError, PathNotFoundError

VALID_TIERS = ("core", "extended", "advanced", "debug", "all")
TEMPLATE_FILES = {
    "part": "Part.PRTDOT",
    "assembly": "Assembly.ASMDOT",
    "drawing": "Drawing.DRWDOT",
}


def _default_output_root() -> Path:
    return Path.home() / "Documents" / "dnk-mcp-solidworks"


def _default_checkpoint_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "dnk-mcp-solidworks"


@dataclass
class Config:
    tool_tier: str = "extended"
    output_root: Path = field(default_factory=_default_output_root)
    allowed_roots: list[Path] = field(default_factory=list)
    checkpoint_root: Path = field(default_factory=_default_checkpoint_root)
    template_dir: Path | None = None
    sw_exe: str | None = None
    auto_checkpoint: bool = True
    checkpoint_debounce_sec: int = 45
    operation_timeout_sec: int = 180
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if self.tool_tier not in VALID_TIERS:
            raise InvalidParameterError(
                f"tool_tier must be one of {', '.join(VALID_TIERS)}"
            )

    def effective_roots(self) -> list[Path]:
        roots = [self.output_root, *self.allowed_roots]
        return [Path(r).expanduser().resolve() for r in roots]

    def resolve_output_path(self, value: str, *, must_exist: bool = False) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.output_root / path
        path = path.resolve()
        if not any(path == root or path.is_relative_to(root) for root in self.effective_roots()):
            raise PathNotAllowedError(
                f"path {path} is outside the allowed roots "
                f"({', '.join(str(r) for r in self.effective_roots())})"
            )
        if must_exist and not path.exists():
            raise PathNotFoundError(f"path does not exist: {path}")
        return path

    def template_dirs(self) -> list[Path]:
        directories: list[Path] = []
        if self.template_dir:
            directories.append(Path(self.template_dir))
        program_data = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        base = program_data / "SOLIDWORKS"
        if base.is_dir():
            directories.extend(sorted(base.glob("SOLIDWORKS */templates")))
        return [directory for directory in directories if directory.is_dir()]

    def discover_template_dir(self) -> Path | None:
        for directory in self.template_dirs():
            return directory
        return None

    def find_template(self, kind: str) -> Path:
        filename = TEMPLATE_FILES.get(kind)
        if filename is None:
            raise InvalidParameterError(
                f"document kind must be one of {', '.join(TEMPLATE_FILES)}"
            )
        for directory in self.template_dirs():
            for candidate in directory.iterdir():
                if candidate.name.lower() == filename.lower():
                    return candidate
        raise PathNotFoundError(
            f"no {filename} found; set SW_MCP_TEMPLATE_DIR to a folder "
            "containing SOLIDWORKS templates"
        )


def _apply_file(config: Config, path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "tool_tier" in data:
        config.tool_tier = str(data["tool_tier"])
    if "output_root" in data:
        config.output_root = Path(data["output_root"]).expanduser()
    if "allowed_roots" in data:
        config.allowed_roots = [Path(p).expanduser() for p in data["allowed_roots"]]
    if "checkpoint_root" in data:
        config.checkpoint_root = Path(data["checkpoint_root"]).expanduser()
    if "template_dir" in data:
        config.template_dir = Path(data["template_dir"]).expanduser()
    if "sw_exe" in data:
        config.sw_exe = str(data["sw_exe"])
    if "auto_checkpoint" in data:
        config.auto_checkpoint = bool(data["auto_checkpoint"])
    if "checkpoint_debounce_sec" in data:
        config.checkpoint_debounce_sec = int(data["checkpoint_debounce_sec"])
    if "operation_timeout_sec" in data:
        config.operation_timeout_sec = int(data["operation_timeout_sec"])
    if "log_level" in data:
        config.log_level = str(data["log_level"])
    config.__post_init__()


def _apply_env(config: Config) -> None:
    if os.environ.get("SW_MCP_TOOL_TIER"):
        config.tool_tier = os.environ["SW_MCP_TOOL_TIER"]
    if os.environ.get("SW_MCP_OUTPUT_ROOT"):
        config.output_root = Path(os.environ["SW_MCP_OUTPUT_ROOT"]).expanduser()
    if os.environ.get("SW_MCP_ALLOWED_ROOTS"):
        config.allowed_roots = [
            Path(p).expanduser()
            for p in os.environ["SW_MCP_ALLOWED_ROOTS"].split(";")
            if p.strip()
        ]
    if os.environ.get("SW_MCP_TEMPLATE_DIR"):
        config.template_dir = Path(os.environ["SW_MCP_TEMPLATE_DIR"]).expanduser()
    if os.environ.get("SW_MCP_SLDWORKS_EXE"):
        config.sw_exe = os.environ["SW_MCP_SLDWORKS_EXE"]
    if os.environ.get("SW_MCP_AUTO_CHECKPOINT"):
        config.auto_checkpoint = os.environ["SW_MCP_AUTO_CHECKPOINT"] not in (
            "0",
            "false",
            "False",
        )
    if os.environ.get("SW_MCP_CHECKPOINT_DEBOUNCE_SEC"):
        config.checkpoint_debounce_sec = int(
            os.environ["SW_MCP_CHECKPOINT_DEBOUNCE_SEC"]
        )
    if os.environ.get("SW_MCP_OPERATION_TIMEOUT_SEC"):
        config.operation_timeout_sec = int(
            os.environ["SW_MCP_OPERATION_TIMEOUT_SEC"]
        )
    if os.environ.get("SW_MCP_LOG_LEVEL"):
        config.log_level = os.environ["SW_MCP_LOG_LEVEL"]
    config.__post_init__()


_config: Config | None = None


def load_config(**overrides) -> Config:
    """Build the effective configuration and remember it as the singleton."""
    global _config
    config = Config()
    config_path = os.environ.get("SW_MCP_CONFIG")
    candidates = []
    if config_path:
        candidates.append(Path(config_path).expanduser())
    else:
        candidates.append(Path.cwd() / "config.local.json")
        candidates.append(Path(__file__).resolve().parents[2] / "config.local.json")
    for candidate in candidates:
        if candidate.is_file():
            _apply_file(config, candidate)
            break
    _apply_env(config)
    for key, item in overrides.items():
        if item is not None:
            setattr(config, key, item)
    config.__post_init__()
    _config = config
    return config


def get_config() -> Config:
    if _config is None:
        return load_config()
    return _config


def setup_logging(config: Config) -> None:
    config.checkpoint_root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(config.checkpoint_root / "server.log", encoding="utf-8"),
        ],
    )
