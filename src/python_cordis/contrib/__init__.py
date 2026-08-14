"""示例插件包：演示 setuptools entry points 自动发现（F1.1b / F11.2）与能力增强。

- :mod:`python_cordis.contrib.demo_plugin`：entry points 自动发现的示例插件。
- :mod:`python_cordis.contrib.web_server`：F16 传输插件（HTTP 上行 + WS 下行）。
- :mod:`python_cordis.contrib.web_frontend`：F16 参考前端静态资源。
- :mod:`python_cordis.contrib.approval`：F17 人机协同工具审批插件。

安装本包（``pip install -e .``）后，
:meth:`python_cordis.HookRegistry.load_entry_points` 会从
``python_cordis.plugins`` 命名空间发现 :data:`plugin`，其 hookimpl 随之生效。
"""
