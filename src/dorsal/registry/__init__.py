from dorsal.registry.initialize import create_new_annotation_model_project
from dorsal.registry.installer import install_model_target
from dorsal.registry.resolution import resolve_target, is_package_installed
from dorsal.registry.uninstaller import uninstall_model_target

__all__ = [
    "create_new_annotation_model_project",
    "install_model_target",
    "resolve_target",
    "is_package_installed",
    "uninstall_model_target",
]
