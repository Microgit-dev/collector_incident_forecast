from .base import RawEvent, SourceAdapter
from .smvu_csv import SmvuCsvAdapter

# Реестр адаптеров: DataSource.adapter ссылается на ключ отсюда
REGISTRY: dict[str, SourceAdapter] = {adapter.key: adapter for adapter in (SmvuCsvAdapter(),)}

__all__ = ["REGISTRY", "RawEvent", "SourceAdapter"]
