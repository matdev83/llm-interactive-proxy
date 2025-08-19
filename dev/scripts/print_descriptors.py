from __future__ import annotations

from pprint import pprint

from src.core.di.services import get_service_collection, get_service_provider


def main() -> int:
    col = get_service_collection()
    descriptors = getattr(col, "_descriptors", {})
    keys = list(descriptors.keys())
    print("DESCRIPTORS_COUNT:", len(keys))
    names = [(getattr(k, "__module__", ""), getattr(k, "__name__", str(k))) for k in keys]
    pprint(names)

    # Check specific services
    try:
        from src.core.interfaces.request_processor_interface import IRequestProcessor
        from src.core.app.controllers.chat_controller import ChatController
        from src.core.services.request_processor_service import RequestProcessor
    except Exception as e:
        print("Import error:", e)
        return 2

    print("IRequestProcessor in descriptors:", IRequestProcessor in descriptors)
    print("RequestProcessor in descriptors:", RequestProcessor in descriptors)
    print("ChatController in descriptors:", ChatController in descriptors)

    # Also check built provider
    try:
        provider = get_service_provider()
        print("ServiceProvider built: True")
        for svc in (IRequestProcessor, RequestProcessor, ChatController):
            try:
                inst = provider.get_service(svc)
                print(f"{getattr(svc,'__name__')} resolvable:", inst is not None)
            except Exception as e:
                print(f"{getattr(svc,'__name__')} resolution error:", e)
    except Exception as e:
        print("Could not build provider:", e)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


