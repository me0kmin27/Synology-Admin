"""Internal HTTP only. No trusted proxy exists in this deployment."""
bind = "0.0.0.0:8000"
workers = 2
threads = 2
timeout = 30
graceful_timeout = 30
worker_tmp_dir = "/tmp"
accesslog = None  # Do not log query strings or invitation credentials.
errorlog = "-"
forwarded_allow_ips = ""
secure_scheme_headers = {}
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190
