from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, BatchSpanProcessor
from opentelemetry.sdk.resources import Resource

def init_tracer():
    resource = Resource(attributes={"service.name": "sstock"})
    provider = TracerProvider(resource=resource)

    # Используем ConsoleSpanExporter вместо OTLPSpanExporter
    processor = BatchSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)
    return trace.get_tracer("my.tracer.name")
