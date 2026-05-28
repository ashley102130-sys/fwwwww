import codecs

with codecs.open('copy_bot.py', 'r', 'utf-8') as f:
    lines = f.readlines()

# lines 37 is index 36, so lines[36] is `# -*- coding: utf-8 -*-`
new_lines = lines[36:851]

append_code = """
import os
import threading
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running perfectly!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

@bot.event
async def on_ready():
    print(f'>>> [1] 機器人登入成功: {bot.user}')
    logger.info(f'>>> [1] 機器人登入成功: {bot.user}')
    print(f'>>> [2] 正在嘗試同步指令...')
    try:
        synced = await bot.tree.sync()
        print(f">>> [3] 同步完成！共同步了 {len(synced)} 個指令。")
        logger.info(f"✅ 成功同步了 {len(synced)} 個斜線指令！")
    except Exception as e:
        print(f">>> [X] 同步過程發生錯誤: {e}")
        logger.error(f"❌ 同步過程發生錯誤: {e}")

@bot.event
async def on_interaction(interaction):
    logger.info(f"收到互動請求: {interaction.type} 來自用戶 {interaction.user}")
    await bot.process_application_commands(interaction)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    print("⏳ Flask 網頁伺服器已在背景啟動...")

    if TOKEN:
        print("⏳ 正在連線至 Discord Gateway...")
        bot.run(TOKEN)
    else:
        print("❌ 錯誤：找不到 DISCORD_TOKEN 環境變數。")
        logger.error("❌ 錯誤：找不到 DISCORD_TOKEN 環境變數。")
"""

with codecs.open('copy_bot.py', 'w', 'utf-8') as f:
    f.writelines(new_lines)
    f.write(append_code)

print("copy_bot.py has been cleaned and fixed!")
