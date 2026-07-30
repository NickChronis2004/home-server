class JarvisError(Exception):
    """Base exception for expected JARVIS failures."""
    error_code = "JARVIS_ERROR"
    http_status = 500
    retryable = False

    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ToolNotFoundError(JarvisError):
    error_code = "TOOL_NOT_FOUND"
    http_status = 404


class ToolTimeoutError(JarvisError):
    error_code = "TOOL_TIMEOUT"
    http_status = 504
    retryable = True


class ToolExecutionError(JarvisError):
    error_code = "TOOL_EXECUTION_FAILED"
    http_status = 500


class ManifestError(JarvisError):
    error_code = "INVALID_TOOL_MANIFEST"
    http_status = 500


class ModelProviderError(JarvisError):
    error_code = "MODEL_PROVIDER_ERROR"
    http_status = 502
    retryable = True
