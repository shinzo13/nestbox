from aiogram import Router

from nestbox.bot.handlers import bind, branch, chat, commands


def build_router() -> Router:
    router = Router(name="root")
    router.include_router(bind.router)
    router.include_router(commands.router)
    router.include_router(branch.router)
    router.include_router(chat.router)
    return router
