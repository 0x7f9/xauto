#!/usr/bin/env python3

import yaml
import threading
import types
from typing import Any, Dict, Optional, Union
from pathlib import Path
from xauto.utils.logging import debug_logger

CONFIG_KEY_ERRORS = (KeyError, TypeError)

class Config:
    _instance: Optional['Config'] = None
    _lock = threading.RLock()
    _config: Union[Dict[str, Any], types.MappingProxyType] = {}
    _config_path: Optional[Path] = None
    _frozen: bool = False
    
    def __new__(cls, config_path: str = "settings.yaml") -> 'Config':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(Config, cls).__new__(cls)
                    cls._instance._load_config(config_path)
        return cls._instance
    
    def _load_config(self, config_path: str) -> None:
        self._config_path = Path(config_path)
        
        if not self._config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        with open(self._config_path, 'r') as f:
            loaded_config = yaml.safe_load(f)
            self._config = loaded_config if loaded_config is not None else {}
    
    @staticmethod
    def get(key_path: str, default: Any = None) -> Any:
        return _global_config._get(key_path, default)
    
    def _get(self, key_path: str, default: Any = None) -> Any:
        keys = key_path.split('.')
        config_dict = dict(self._config) if self._frozen else self._config
        value: Any = config_dict
        
        try:
            for i, key in enumerate(keys):
                if isinstance(value, dict):
                    value = value[key]
                else:
                    partial_path = '.'.join(keys[:i+1])
                    debug_logger.debug(f"Config path traversal failed at '{partial_path}': value is {type(value).__name__}, not dict")
                    return default
            return value
        except CONFIG_KEY_ERRORS as e:
            debug_logger.debug(f"Config key '{key_path}' not found: {e}")
            return default
    
    def get_nested(self, *keys: str, default: Any = None) -> Any:
        return self._get('.'.join(keys), default)
    
    def get_section(self, section: str) -> Dict[str, Any]:
        config_dict = dict(self._config) if self._frozen else self._config
        return config_dict.get(section, {})
    
    def has_key(self, key_path: str) -> bool:
        keys = key_path.split('.')
        config_dict = dict(self._config) if self._frozen else self._config
        value: Any = config_dict
        
        try:
            for key in keys:
                if isinstance(value, dict):
                    value = value[key]
                else:
                    return False
            return True
        except CONFIG_KEY_ERRORS:
            return False
    
    def freeze(self) -> None:
        with self._lock:
            if not self._frozen:
                self._config = types.MappingProxyType(self._config)
                self._frozen = True
                debug_logger.info("Configuration frozen - no further modifications allowed")
    
    def is_frozen(self) -> bool:
        return self._frozen
    
    @property
    def config_path(self) -> Optional[Path]:
        return self._config_path
    
    @property
    def raw_config(self) -> Dict[str, Any]:
        return self._config.copy()
    
    def __getitem__(self, key: str) -> Any:
        return self._config[key]
    
    def __contains__(self, key: str) -> bool:
        return key in self._config
    
    def __repr__(self) -> str:
        frozen_status = " (frozen)" if self._frozen else ""
        return f"Config(path={self._config_path}{frozen_status})"

_global_config = Config("settings.yaml")

# def is_debug_mode():
#     cfg = get_global_config()
#     return bool(cfg.get('misc.debug_mode', False))