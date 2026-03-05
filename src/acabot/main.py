import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("acabot")


def main():
    logger.info("AcaBot starting...")
    asyncio.run(_run())


async def _run():
    logger.info("AcaBot running. Press Ctrl+C to stop.")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("AcaBot stopped.")


if __name__ == "__main__":
    main()
