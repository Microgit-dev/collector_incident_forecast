from .base import RawEvent, SourceAdapter
from .smvu_csv import SmvuCsvAdapter
from .smvu_xlsx import SmvuXlsxAdapter

# Реестр адаптеров: DataSource.adapter ссылается на ключ отсюда
REGISTRY: dict[str, SourceAdapter] = {
    adapter.key: adapter for adapter in (SmvuCsvAdapter(), SmvuXlsxAdapter())
}

__all__ = ["REGISTRY", "RawEvent", "SourceAdapter"]
