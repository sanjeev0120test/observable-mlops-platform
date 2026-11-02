"""Keep the unit-test process from opening OTLP exporters.

Service modules start telemetry on import. With the SDK installed and no
collector, those exporters retry against localhost and slow the run. The
telemetry tests clear this flag and use in-memory exporters.
"""

import os

os.environ.setdefault("OTEL_SDK_DISABLED", "true")
