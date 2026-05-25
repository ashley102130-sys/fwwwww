# -*- coding: utf-8 -*-
from asyncio import subprocess
from asyncio import subprocess
import asyncio
import sys

# ✅ 修正 Windows 上 aiohttp DNS 解析失敗的問題 (ProactorEventLoop 不相容)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
import discord
from discord.ext import commands, tasks
import random

import os
import aiohttp
import logging
from dotenv import load_dotenv

# 加載 .env 檔案
load_dotenv()

# 配置日誌系統，同時輸出到檔案與終端
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("fw_bot")

# ====================== 修改這裡 ======================

# 從環境變數讀取 TOKEN
def load_token():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("❌ 找不到 DISCORD_TOKEN 環境變數，請檢查 .env 檔案")
        return ""
    return token.strip()

TOKEN = load_token()

# 預設發送內容列表
MESSAGES = [
    "@everyone 好緊張", 
    "@everyone 廢物",
]

# 動態追蹤要在哪些頻道/使用者洗頻，並記錄各自的訊息
active_spam_channels = {} # {id: {"obj": channel, "msg": str}}
active_webhooks = {}      # {url: {"nick": nickname, "msg": str}}
active_audio_guilds = set() # {guild_id} - 記錄哪些伺服器正在無限輪播爆音板
active_use_spams = {}     # {channel_id: asyncio.Task}
active_channel_webhooks = {}  # {channel_id: [webhook_url1, webhook_url2, ...]}

async def send_raw_followup(session, app_id, token, content):
    url = f"https://discord.com/api/v10/webhooks/{app_id}/{token}"
    payload = {"content": content}
    try:
        async with session.post(url, json=payload) as resp:
            return resp.status
    except Exception as e:
        return e


async def prepare_channel_webhooks(channel):
    if channel.id in active_channel_webhooks:
        return active_channel_webhooks[channel.id]
    
    urls = []
    try:
        if hasattr(channel, "permissions_for") and hasattr(channel, "guild"):
            permissions = channel.permissions_for(channel.guild.me)
            if not permissions.manage_webhooks:
                return []
                
            existing = await channel.webhooks()
            # 找出我們 bot 建立的 webhook
            our_webhooks = [w for w in existing if w.user and w.user.id == bot.user.id]
            
            while len(our_webhooks) < 3:
                name = f"FW_Hook_{random.randint(1000, 9999)}"
                new_hook = await channel.create_webhook(name=name)
                our_webhooks.append(new_hook)
                await asyncio.sleep(0.1)
                
            urls = [w.url for w in our_webhooks[:3]]
            active_channel_webhooks[channel.id] = urls
    except Exception as e:
        logger.warning(f"無法為頻道 {channel.name} ({channel.id}) 建立 Webhook: {e}")
        
    return urls

# =======================================================

class MyBot(commands.Bot):
    def __init__(self):
        # Intents.default() 並不包含成員（Members）資訊
        intents = discord.Intents.default()
        intents.message_content = True # 啟用讀取訊息內容的權限
        intents.members = True         # 啟用獲取伺服器成員資料的權限
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # 開機時同步 slash commands 到 Discord 伺服器
        await self.tree.sync()
        logger.info("✅ 斜線指令同步完成！")
        
        # 檢查 Opus 狀態
        if not discord.opus.is_loaded():
            logger.info("正在檢查 Opus 編解碼器...")
            opus_libs = ['libopus-0.x64.dll', 'libopus-0.dll', 'opus.dll', 'libopus.dll']
            for lib in opus_libs:
                try:
                    discord.opus.load_opus(lib)
                    logger.info(f"✅ 成功載入 Opus: {lib}")
                    break
                except :
                    continue
            
            if not discord.opus.is_loaded():
                logger.warning("⚠️ 找不到 Opus DLL，語音功能（播放音樂）可能無法執行。")
                logger.warning("提示：這在 Windows 上很常見，通常不需要理會，除非你發現 /laugh 沒有聲音。")
        else:
            logger.info("✅ Opus 編解碼器已就緒")

bot = MyBot()

@bot.event
async def on_ready():
    logger.info(f"✅ 成功登入為 {bot.user} (ID: {bot.user.id})")
    logger.info("🤖 機器人已準備就緒！")
    logger.info("可用指令：/use, /nuke, /raid, /stop, /stop_all, /clear, /webhook_use")

@bot.event
async def on_voice_state_update(member, before, after):
    # 如果是機器人自己變更狀態，不處理
    if member.bot:
        return

    # 取得該伺服器的語音連線狀態
    voice_client = member.guild.voice_client
    if not voice_client or not voice_client.is_connected():
        return

    # 當有人離開語音頻道，且該頻道是機器人所在的頻道
    if before.channel and before.channel.id == voice_client.channel.id:
        # 計算頻道內還有多少真人
        non_bot_members = [m for m in voice_client.channel.members if not m.bot]
        
        # 如果已經沒有真人了，自動退出
        if len(non_bot_members) == 0:
            logger.info(f"語音頻道 {voice_client.channel.name} 已無其他成員，機器人自動退出。")
            await voice_client.disconnect()
            
            # 如果爆音板輪播功能正在該伺服器運行，也一併停止
            if member.guild.id in active_audio_guilds:
                active_audio_guilds.discard(member.guild.id)
@bot.tree.command(name="raid", description="💣 突擊模式：給機器人邀請連結，它會自動加入並立即對所有頻道開炸")
@discord.app_commands.describe(invite="伺服器邀請連結 (例如: https://discord.gg/abc123)", content="自訂炸頻內容 (選填)")
async def raid_command(interaction: discord.Interaction, invite: str, content: str = None):
    await interaction.response.defer(ephemeral=True)
    
    # 解析邀請碼
    invite = invite.strip()
    code = invite.split("/")[-1]  # 取出邀請碼部分
    
    try:
        # 用 aiohttp 直接呼叫 Discord API 接受邀請（機器人自動加入）
        headers = {
            "Authorization": f"Bot {TOKEN}",
            "Content-Type": "application/json"
        }
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"https://discord.com/api/v10/invites/{code}",
                headers=headers
            )
            data = await resp.json()
        
        if resp.status not in (200, 201):
            error_msg = data.get("message", "未知錯誤")
            await interaction.followup.send(f"❌ **加入失敗！** Discord 回傳錯誤：`{error_msg}` (狀態碼: {resp.status})", ephemeral=True)
            return
        
        guild_id = int(data.get("guild", {}).get("id", 0))
        guild_name = data.get("guild", {}).get("name", "未知伺服器")
        logger.info(f"突擊指令：成功加入伺服器 {guild_name} ({guild_id})")
        
        # 等一下讓 bot.get_guild 快取同步
        await asyncio.sleep(2)
        
        guild = bot.get_guild(guild_id)
        if not guild:
            await interaction.followup.send(f"⚠️ 已發送加入請求到 **{guild_name}**，但快取尚未同步。請等幾秒後手動使用 `/nuke`。", ephemeral=True)
            return
        
        # 立刻加入所有頻道並開始炸
        count = 0
        for channel in guild.text_channels:
            if channel.id not in active_spam_channels:
                active_spam_channels[channel.id] = {"obj": channel, "msg": content}
                count += 1
        
        if count > 0:
            if not spam_task.is_running():
                spam_task.start()
            msg_info = f"內容: `{content}`" if content else "內容: `隨機預設`"
            await interaction.followup.send(f"💣 **突擊成功！**\n已加入伺服器 **{guild_name}** 並在 `{count}` 個頻道開炸！\n{msg_info}", ephemeral=True)
            logger.info(f"突擊指令：在 {guild_name} 的 {count} 個頻道開始發送")
        else:
            await interaction.followup.send(f"✅ 已加入 **{guild_name}**，但找不到可發言的頻道。", ephemeral=True)
    
    except Exception as e:
        logger.exception("突擊指令發生錯誤")
        await interaction.followup.send(f"❌ 發生錯誤：{e}", ephemeral=True)

class SpamButtonView(discord.ui.View):
    def __init__(self, content):
        super().__init__(timeout=None)
        self.content = content

    @discord.ui.button(label="💥 點一次發 5 條", style=discord.ButtonStyle.danger, custom_id="spam_btn_burst5")
    async def burst5_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        msg = self.content if self.content else random.choice(MESSAGES)

        async with aiohttp.ClientSession() as session:
            tasks = [send_raw_followup(session, interaction.application_id, interaction.token, msg) for _ in range(5)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        count = sum(1 for r in results if r in (200, 201, 204))
        try:
            await interaction.followup.send(f"✅ 成功發送 {count} 條！", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="🚀 開啟自動連發", style=discord.ButtonStyle.success, custom_id="spam_btn_start_auto")
    async def start_auto_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        cid = interaction.channel_id

        # 如果已經在發送，先停止舊的
        if cid in active_use_spams:
            active_use_spams[cid].cancel()

        msg = self.content if self.content else None

        # 啟動自動連發協程，傳入 app_id 與 token
        task = asyncio.create_task(
            self.auto_spam_loop(cid, interaction.application_id, interaction.token, msg)
        )
        active_use_spams[cid] = task

        try:
            await interaction.followup.send("🚀 **自動連發已啟動！** 正在背景持續發送中...", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="🛑 停止自動連發", style=discord.ButtonStyle.secondary, custom_id="spam_btn_stop_auto")
    async def stop_auto_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        cid = interaction.channel_id

        if cid in active_use_spams:
            active_use_spams[cid].cancel()
            del active_use_spams[cid]
            try:
                await interaction.followup.send("🛑 **已成功停止自動連發！**", ephemeral=True)
            except Exception:
                pass
        else:
            try:
                await interaction.followup.send("⚠️ 此頻道目前沒有正在運行的自動連發任務喔！", ephemeral=True)
            except Exception:
                pass

    async def auto_spam_loop(self, channel_id, app_id, token, content):
        """純 Interaction Followup 自動連發，無需任何伺服器權限。"""
        try:
            async with aiohttp.ClientSession() as session:
                while True:
                    msg = content if content else random.choice(MESSAGES)
                    # 每輪同時發送 5 條，不需要任何伺服器權限
                    tasks = [send_raw_followup(session, app_id, token, msg) for _ in range(5)]
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[auto_spam_loop] 發生錯誤: {e}")


@bot.tree.command(name="use", description="召喚無權限自動發送面板（支援使用者安裝，不需加入伺服器）")
@discord.app_commands.allowed_installs(guilds=True, users=True)
@discord.app_commands.allowed_contexts(guilds=True, dms=False, private_channels=True)
@discord.app_commands.describe(content="自訂發送內容 (選填)")
async def use_command(interaction: discord.Interaction, content: str = None):
    view = SpamButtonView(content)
    await interaction.response.send_message(
        "🛠️ **無權限發送面板已就緒！**\n"
        "👉 **點擊「開啟自動連發」** 在背景持續發送訊息\n"
        "👉 **點擊「停止自動連發」** 隨時停止",
        view=view,
        ephemeral=True
    )
    logger.info(f"指令：/use 啟動了無權限發送面板，內容: {content}")


@bot.tree.command(name="stop", description="停止在此頻道或指定頻道自動發送訊息")
@discord.app_commands.describe(target_id="目標頻道 ID (如果要停止遙控的頻道，請提供 ID)")
async def stop_command(interaction: discord.Interaction, target_id: str = None):
    # 定義目標 ID
    cid = int(target_id) if target_id else interaction.channel_id
    
    stopped = False
    
    if cid in active_spam_channels:
        channel_name = active_spam_channels[cid]["obj"].name
        del active_spam_channels[cid]
        stopped = True
        logger.info(f"指令：停止在頻道 {channel_name} ({cid}) 發送")
        if not active_spam_channels and spam_task.is_running():
            spam_task.stop()

    if cid in active_use_spams:
        active_use_spams[cid].cancel()
        del active_use_spams[cid]
        stopped = True
        logger.info(f"指令：停止在頻道 {cid} 的 /use 自動連發")

    if stopped:
        await interaction.response.send_message(f"🛑 已停止在頻道 `{cid}` 的所有自動發送任務", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ ID `{cid}` 的頻道目前沒有任何活動的發送任務喔！", ephemeral=True)

@bot.tree.command(name="nuke", description="⛔ 核彈模式：刪除頻道、新建頻道並修改伺服器名稱 (極端危險)")
@discord.app_commands.describe(
    content="自訂炸頻內容 (選填)", 
    count="要建立的新頻道數量 (預設 20)", 
    channel_name="新頻道名稱 (選填)",
    server_name="新的伺服器名稱 (選填)"
)
async def nuke_command(
    interaction: discord.Interaction, 
    content: str = None, 
    count: int = 20, 
    channel_name: str = "nuclear-strike",
    server_name: str = None
):
    guild = interaction.guild
    if not guild:
         await interaction.response.send_message("❌ 此指令只能在伺服器內使用！", ephemeral=True)
         return
         
    # 防止按鈕連點或誤觸
    await interaction.response.defer(ephemeral=False)
    await interaction.followup.send("⚠️ **毀滅模式啟動中...** 正在執行伺服器重組程序！")
    
    # 修改伺服器名稱
    if server_name:
        try:
            await guild.edit(name=server_name)
            logger.info(f"核彈指令：更改伺服器名稱為 {server_name}")
        except Exception as e:
            logger.warning(f"核彈指令：修改伺服器名稱失敗: {e}")

    # 停止現有的發送任務，避免報錯
    active_spam_channels.clear()
    if spam_task.is_running():
        spam_task.stop()

    deleted_count = 0
    created_count = 0

    # 1. 刪除所有可見頻道 (平行刪除以加快速度)
    delete_tasks = []
    for channel in guild.channels:
        delete_tasks.append(channel.delete())
        
    if delete_tasks:
        results = await asyncio.gather(*delete_tasks, return_exceptions=True)
        deleted_count = sum(1 for r in results if not isinstance(r, Exception))

    # 2. 建立新頻道 (平行建立以加快速度)
    create_tasks = []
    # 限制最大建立數量以免被 Discord API Block
    count = max(1, min(count, 50))
    for _ in range(count):
        create_tasks.append(guild.create_text_channel(name=channel_name))
        
    created_channels = []
    if create_tasks:
        results = await asyncio.gather(*create_tasks, return_exceptions=True)
        for r in results:
            if not isinstance(r, Exception):
                created_channels.append(r)
                created_count += 1
                
    # 3. 將新頻道加入轟炸名單
    for c in created_channels:
        active_spam_channels[c.id] = {"obj": c, "msg": content}
        
    if active_spam_channels and not spam_task.is_running():
        spam_task.start()
        
    logger.info(f"核彈指令：已在 {guild.name} 刪除 {deleted_count} 個頻道，建立 {created_count} 個新頻道開始發送！")

@bot.tree.command(name="stop_all", description="🛑 停火協定：停止目前伺服器內所有發送任務")
async def stop_all_command(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ 此指令只能在伺服器內使用！", ephemeral=True)
        return

    removed_count = 0
    # 停止 active_spam_channels 任務
    for cid, data in list(active_spam_channels.items()):
        if data["obj"].guild.id == guild.id:
            del active_spam_channels[cid]
            removed_count += 1
            
    # 停止 active_use_spams 任務
    for channel in guild.text_channels:
        if channel.id in active_use_spams:
            active_use_spams[channel.id].cancel()
            del active_use_spams[channel.id]
            removed_count += 1

    if removed_count > 0:
        await interaction.response.send_message(f"🛑 已停止伺服器內 `{removed_count}` 個發送任務。", ephemeral=True)
        if not active_spam_channels and spam_task.is_running():
            spam_task.stop()
    else:
        await interaction.response.send_message("⚠️ 此伺服器目前沒有正在進行的發送任務。", ephemeral=True)


@bot.tree.command(name="clear", description="快速清理當前頻道的訊息")
@discord.app_commands.describe(amount="要刪除的訊息數量 (預設 100)")
async def clear_command(interaction: discord.Interaction, amount: int = 100):
    # 因為刪除訊息可能需要一點時間，先 defer 回應避免 Timeout 錯誤
    await interaction.response.defer(ephemeral=True)
    try:
        # purge 會刪除指定數量的訊息
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"✅ 成功清理了 {len(deleted)} 則訊息！", ephemeral=True)
        logger.info(f"在頻道 {interaction.channel.name} 清理了 {len(deleted)} 則訊息")
    except discord.Forbidden:
        await interaction.followup.send("❌ 我沒有權限刪除訊息 (需要「管理訊息」權限)。", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ 發生錯誤：{e}", ephemeral=True)

@bot.tree.command(name="webhook_use", description="使用 Webhook URL 啟動自動發送")
@discord.app_commands.describe(url="Webhook 網址", nickname="顯示名字", content="發送內容 (選填)")
async def webhook_use_command(interaction: discord.Interaction, url: str, nickname: str = "FW_Bot", content: str = None):
    url = url.strip()
    if not url.startswith("https://discord.com/api/webhooks/"):
        await interaction.response.send_message("❌ 無效的 Webhook 網址！", ephemeral=True)
        return

    if url in active_webhooks:
        await interaction.response.send_message("⚠️ 這個 Webhook 已經在發送中了！", ephemeral=True)
        return

    active_webhooks[url] = {"nick": nickname, "msg": content}
    
    if not webhook_spam_task.is_running():
        webhook_spam_task.start()
        
    msg_info = f"内容: `{content}`" if content else "内容: `隨機預設`"
    await interaction.response.send_message(f"🚀 **Webhook 模式啟動！**\n{msg_info}", ephemeral=True)
    logger.info(f"Webhook 指令：開始在 {url} 發送 ({msg_info})")

@bot.tree.command(name="webhook_stop", description="停止指定的 Webhook 自動發送")
@discord.app_commands.describe(url="要停止的 Webhook 完整網址")
async def webhook_stop_command(interaction: discord.Interaction, url: str):
    url = url.strip()
    if url in active_webhooks:
        del active_webhooks[url]
        await interaction.response.send_message("🛑 已停止該 Webhook 的自動發送。", ephemeral=True)
        logger.info(f"Webhook 指令：停止在 {url} 發送")
        
        if not active_webhooks and webhook_spam_task.is_running():
            webhook_spam_task.stop()
    else:
        await interaction.response.send_message("⚠️ 該 Webhook 目前沒有在自動發送喔！", ephemeral=True)

class DMSpamButtonView(discord.ui.View):
    def __init__(self, target_user, content):
        super().__init__(timeout=None)
        self.target_user = target_user
        self.content = content

    @discord.ui.button(label="💥 點一次發射 10 條私訊", style=discord.ButtonStyle.danger)
    async def spam_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        msg = self.content if self.content else random.choice(MESSAGES)
        
        # 平行發送所有私訊
        tasks = [self.target_user.send(msg) for _ in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        count = sum(1 for r in results if not isinstance(r, Exception))
        
        try:
            if count > 0:
                await interaction.followup.send(f"✅ 成功對 `{self.target_user.name}` 發送 {count} 條！", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ 無法發送私訊給 `{self.target_user.name}`，可能對方關閉了私訊或機器人被封鎖。", ephemeral=True)
        except Exception:
            pass  # 429 rate limit，確認訊息失敗無視


@bot.tree.command(name="dm_spam", description="🎯 私聊轟炸：對指定使用者開啟炸頻控制面板")
@discord.app_commands.describe(user_id="目標 ID", content="自訂內容 (選填)")
async def dm_spam_command(interaction: discord.Interaction, user_id: str, content: str = None):
    user_id = user_id.strip()
    try:
        uid = int(user_id)
        user = bot.get_user(uid)
        if user is None: user = await bot.fetch_user(uid)
    except:
        await interaction.response.send_message("❌ 找不到使用者！請確認 ID 是否正確。", ephemeral=True)
        return

    view = DMSpamButtonView(user, content)
    await interaction.response.send_message(
        f"🎯 **私聊轟炸面板已就緒！** 目標: `{user.name}`\n"
        "每次點擊最多私聊發送 10 條。\n"
        "👇 **請點擊下方按鈕**", 
        view=view, 
        ephemeral=True
    )
    logger.info(f"指令：/dm_spam 啟動了對 {user.name} 的控制面板")

class RandomFileView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎲 再抽一個", style=discord.ButtonStyle.secondary)
    async def reroll_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        library_path = "library"
        files = [f for f in os.listdir(library_path) if os.path.isfile(os.path.join(library_path, f))]
        if not files:
            await interaction.response.send_message("❌ `library` 資料夾是空的！", ephemeral=True)
            return

        selected_file = random.choice(files)
        file_path = os.path.join(library_path, selected_file)

        try:
            await interaction.response.defer()
            await interaction.followup.send(
                f"🎲 再抽一次: `{selected_file}`",
                file=discord.File(file_path),
                view=RandomFileView()
            )
            logger.info(f"[再抽] 發送了 {selected_file}")
        except Exception as e:
            await interaction.followup.send(f"❌ 發送失敗：{e}", ephemeral=True)

@bot.tree.command(name="send_file", description="📁 隨機發送 library 資料夾中的一個檔案到聊天室")
async def send_file_command(interaction: discord.Interaction):
    library_path = "library"
    if not os.path.exists(library_path):
        await interaction.response.send_message("❌ 找不到 `library` 資料夾！", ephemeral=True)
        return

    files = [f for f in os.listdir(library_path) if os.path.isfile(os.path.join(library_path, f))]
    if not files:
        await interaction.response.send_message("❌ `library` 資料夾是空的！", ephemeral=True)
        return

    selected_file = random.choice(files)
    file_path = os.path.join(library_path, selected_file)

    try:
        await interaction.response.defer()
        await interaction.followup.send(
            f"🎲 隨機抽到: `{selected_file}`",
            file=discord.File(file_path),
            view=RandomFileView()
        )
        logger.info(f"指令：/send_file 發送了 {selected_file} 到 {interaction.channel}")
    except Exception as e:
        await interaction.followup.send(f"❌ 發送失敗：{e}", ephemeral=True)
        logger.exception(f"send_file 失敗: {e}")

@bot.tree.command(name="set_msg", description="⚙️ 全局設定：更改預設的炸頻內容清單 (使用空格分隔多條內容)")
@discord.app_commands.describe(text="範例: 內容一 內容二 內容三 (機器人會隨機挑選發送)")
async def set_msg_command(interaction: discord.Interaction, text: str):
    global MESSAGES
    new_msgs = [m.strip() for m in text.split(" ") if m.strip()]
    if not new_msgs:
        await interaction.response.send_message("❌ 內容不能為空！", ephemeral=True)
        return
    
    MESSAGES = new_msgs
    await interaction.response.send_message(f"✅ 預設內容已更新！現在包含 `{len(MESSAGES)}` 條訊息。", ephemeral=True)
    logger.info(f"指令：更新全局訊息清單為: {MESSAGES}")

BURST_PER_TICK = 3  # 每次 tick 每個頻道發送幾條（調高=更快，但容易被 rate limit）

@tasks.loop(seconds=0.2)  # 優化為 0.2 秒一次
async def spam_task():
    if not active_spam_channels:
        return

    async with aiohttp.ClientSession() as session:
        tasks_to_run = []
        
        for cid, data in list(active_spam_channels.items()):
            channel = data["obj"]
            msg = data["msg"] if data["msg"] else random.choice(MESSAGES)
            
            # 獲取或建立 Webhook
            urls = await prepare_channel_webhooks(channel)
            
            if urls:
                # 使用 Webhook 發送
                for url in urls:
                    # 每個 Webhook 在每個 tick 發 2 條
                    for _ in range(2):
                        payload = {
                            "content": msg,
                            "username": "ORRICAC_FW"
                        }
                        tasks_to_run.append(session.post(url, json=payload))
            else:
                # 回退到標準發送
                for _ in range(BURST_PER_TICK):
                    tasks_to_run.append(channel.send(msg))
                    
        if tasks_to_run:
            results = await asyncio.gather(*tasks_to_run, return_exceptions=True)
            fails = 0
            for r in results:
                if isinstance(r, Exception):
                    fails += 1
                elif hasattr(r, 'status') and r.status not in (200, 201, 204):
                    fails += 1
            if fails:
                logger.warning(f"[spam_task] {fails}/{len(tasks_to_run)} 條發送失敗（可能 rate limit）")

@tasks.loop(seconds=0.5)  # 原本 1.0s，改為 0.5s
async def webhook_spam_task():
    if not active_webhooks:
        return

    async with aiohttp.ClientSession() as session:
        tasks_to_run = []
        for url, data in list(active_webhooks.items()):
            # 每個 webhook 也一次打 BURST_PER_TICK 條
            for _ in range(BURST_PER_TICK):
                msg = data["msg"] if data["msg"] else random.choice(MESSAGES)
                payload = {
                    "content": msg,
                    "username": data["nick"]
                }
                tasks_to_run.append(session.post(url, json=payload))
            
        if tasks_to_run:
            await asyncio.gather(*tasks_to_run, return_exceptions=True)

@bot.tree.command(name="join", description="讓機器人加入你所在的語音頻道")
async def join_command(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ 你必須先加入一個語音頻道！", ephemeral=True)
        return
        
    channel = interaction.user.voice.channel
    
    # 檢查是否已經在頻道內
    if interaction.guild.voice_client:
        if interaction.guild.voice_client.channel.id == channel.id:
            await interaction.response.send_message("⚠️ 我已經在這個頻道裡了！", ephemeral=True)
            return
        else:
            # 移動到新頻道
            await interaction.guild.voice_client.move_to(channel)
            await interaction.response.send_message(f"🏃 已移動到語音頻道: {channel.name}")
            return

    # 加入頻道
    await channel.connect()
    await interaction.response.send_message(f"✅ 已成功加入語音頻道: {channel.name}")

@bot.tree.command(name="leave", description="讓機器人離開語音頻道")
async def leave_command(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("👋 已離開語音頻道！")
    else:
        await interaction.response.send_message("⚠️ 我目前不在任何語音頻道裡喔！", ephemeral=True)

class AudioControlView(discord.ui.View):
    def __init__(self):
        # 設定為 None，讓按鈕永遠不會過期失效
        super().__init__(timeout=None)

    @discord.ui.button(label="⏭️ 跳過當前音檔", style=discord.ButtonStyle.primary)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()
            await interaction.response.send_message("⏭️ 已跳過！正在切換下一首...", ephemeral=True)
            logger.info(f"使用者 {interaction.user.name} 點擊了跳過音檔")
        else:
            await interaction.response.send_message("⚠️ 目前沒有正在播放的音檔喔！", ephemeral=True)

@bot.tree.command(name="laugh", description="開啟/關閉無限播放資料庫中的爆音板")
async def laugh_command(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    
    if guild_id in active_audio_guilds:
        # 如果已經在播，就馬上關掉
        active_audio_guilds.remove(guild_id)
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()
        await interaction.response.send_message("🛑 **已停止爆音板無限輪播！**")
        logger.info(f"指令：在伺服器 {interaction.guild.name} 停止輪播爆音板")
        return

    logger.info(f"收到 `/laugh` 指令，開始在 {interaction.guild.name} 無限輪播")
    
    # 確保已經連上語音
    voice_client = interaction.guild.voice_client
    if not voice_client:
        await interaction.response.send_message("❌ 我還沒加入語音頻道！請先使用 `/join`", ephemeral=True)
        return

    # 檢查語音連線狀態
    if not voice_client.is_connected():
        await interaction.response.send_message("❌ 語音連線異常，請嘗試重新 `/join`", ephemeral=True)
        return

    library_path = "library"
    if not os.path.exists(library_path) or not os.listdir(library_path):
        await interaction.response.send_message("❌ 找不到 `library` 資料夾，或裡面沒有任何音檔！", ephemeral=True)
        return

    # 加入活躍名單
    active_audio_guilds.add(guild_id)
    view = AudioControlView()
    await interaction.response.send_message(
        "🔊 **已開啟無限輪播模式！** (再次輸入 `/laugh` 即可停止)\n"
        "👇 點擊下方按鈕可以跳過當前正在播放的音檔。",
        view=view
    )
    
    # 啟動輪播機制
    play_next_audio(interaction.guild)

def play_next_audio(guild: discord.Guild):
    # 只有繼續在活躍清單裡才播放
    if guild.id not in active_audio_guilds:
        return
        
    voice_client = guild.voice_client
    if not voice_client or not voice_client.is_connected():
        active_audio_guilds.discard(guild.id)
        return
        
    library_path = "library"
    files = [f for f in os.listdir(library_path) if f.endswith(('.wav', '.mp3', '.ogg'))]
    if not files:
        active_audio_guilds.discard(guild.id)
        return
        
    selected_file = random.choice(files)
    file_path = os.path.join(library_path, selected_file)
    
    try:
        ffmpeg_options = {'options': '-vn'}
        ffmpeg_executable = "ffmpeg"
        if os.path.exists("./ffmpeg.exe"):
            ffmpeg_executable = "./ffmpeg.exe"
            
        audio_source = discord.FFmpegPCMAudio(
            executable=ffmpeg_executable,
            source=file_path,
            **ffmpeg_options
        )
        
        # 播放完畢後的回呼函數
        def after_playing(error):
            if error:
                logger.error(f"[輪播錯誤] {error}")
            if guild.id in active_audio_guilds:
                bot.loop.call_later(0.1, play_next_audio, guild)  # 0.1s 接續下一首（原本 1.0s）

        if not voice_client.is_playing():
            voice_client.play(audio_source, after=after_playing)
            logger.info(f"[輪播] 正在伺服器 {guild.name} 播放: {selected_file}")
            
    except Exception as e:
        logger.exception(f"[輪播失敗] {e}")
        # 如果出錯，過幾秒再試一次
        bot.loop.call_later(3.0, play_next_audio, guild)

import os
import discord
from flask import Flask
from threading import Thread

# 1. 建立 Flask 網頁伺服器，讓 Render 偵測到 Port
app = Flask('')

@app.route('/')
def home():
    return "機器人 24H 運作中！"

def run():
    # 從 Render 環境變數讀取 PORT，沒讀到則預設 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# 2. Discord 機器人設定
# 記得要在 Discord Developer Portal 開啟 Message Content Intent
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'[成功] 登入為 {client.user}')

# 3. 執行部分
if __name__ == "__main__":
    # 先啟動背景網頁伺服器
    keep_alive()
    
    # 讀取你在 Render 後台 Environment 設定的 TOKEN
    token = os.environ.get('TOKEN')
    if token:
        client.run(token)
    else:
        print("錯誤：找不到 TOKEN 環境變數，請檢查 Render 的 Environment 設定。")