import os
from fastapi import FastAPI
from bot.api_admin import router as admin_router
from bot.api_webhook import router as webhook_router
app = FastAPI()
app.include_router(admin_router)
app.include_router(webhook_router)
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8080')))