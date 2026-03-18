# dashboard/__init__.py
#
# Marks this directory as a Python package and sets the default AppConfig
# so Django picks up DashboardConfig (which wires up signal receivers) when
# the application is loaded.

default_app_config = "dashboard.apps.DashboardConfig"
