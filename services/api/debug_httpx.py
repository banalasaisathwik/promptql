import asyncio
import httpx


async def main():
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get("https://openrouter.ai/api/v1/models")
        print("status:", response.status_code)


asyncio.run(main())