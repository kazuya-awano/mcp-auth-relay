from dify_plugin import Plugin, DifyPluginEnv
from tools.utils.debug import debug_event

plugin = Plugin(DifyPluginEnv(MAX_REQUEST_TIMEOUT=120))

if __name__ == '__main__':
    debug_event("debug_logging_enabled")
    plugin.run()
