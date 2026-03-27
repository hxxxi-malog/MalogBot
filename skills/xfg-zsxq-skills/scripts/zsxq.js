#!/usr/bin/env node

/**
 * 知识星球 CLI 工具 v2.0
 * 支持多星球配置 + 图片上传（最多9张）
 *
 * 命令：
 *   node zsxq.js config add    --url "https://wx.zsxq.com/group/ID" --cookie "..."
 *   node zsxq.js config list
 *   node zsxq.js post          --text "内容" [--images "/path/a.jpg,/path/b.png"]
 *   node zsxq.js post          --file "/path/post.txt" --images "/path/a.jpg"
 */

const https = require('https');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const os = require('os');

// 配置文件路径
const CONFIG_DIR = path.join(os.homedir(), '.xfg-zsxq');
const CONFIG_FILE = path.join(CONFIG_DIR, 'groups.json');

// ─── 颜色输出 ────────────────────────────────────────────
const R = '\x1b[31m', G = '\x1b[32m', Y = '\x1b[33m', B = '\x1b[36m', N = '\x1b[0m';
const ok  = (m) => console.log(`${G}✓ ${m}${N}`);
const err = (m) => console.error(`${R}✗ ${m}${N}`);
const inf = (m) => console.log(`${B}ℹ ${m}${N}`);

// ─── 工具函数 ────────────────────────────────────────────
function loadConfig() {
    try {
        return fs.existsSync(CONFIG_FILE)
            ? JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'))
            : { default: null, groups: {} };
    } catch { return { default: null, groups: {} }; }
}

function saveConfig(cfg) {
    if (!fs.existsSync(CONFIG_DIR)) fs.mkdirSync(CONFIG_DIR, { recursive: true });
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(cfg, null, 2), { mode: 0o600 });
}

function extractGroupId(url) {
    const m = url.match(/\/group\/(\d+)/);
    return m ? m[1] : null;
}

function genSig(timestamp, body) {
    const md5 = crypto.createHash('md5').update(body || '').digest('hex');
    return crypto.createHash('sha1').update(timestamp + md5).digest('hex');
}

function genUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
    });
}

// 生成 x-aduid（广告用户ID，格式：a + 随机字符串）
function genAduid() {
    const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
    let result = 'a';
    for (let i = 0; i < 8; i++) result += chars[Math.floor(Math.random() * chars.length)];
    result += '-';
    for (let i = 0; i < 4; i++) result += chars[Math.floor(Math.random() * chars.length)];
    result += '-';
    for (let i = 0; i < 4; i++) result += chars[Math.floor(Math.random() * chars.length)];
    result += '-';
    for (let i = 0; i < 12; i++) result += chars[Math.floor(Math.random() * chars.length)];
    return result;
}

// ─── HTTP 请求 ───────────────────────────────────────────
function httpReq(opts, body) {
    return new Promise((resolve, reject) => {
        const req = https.request(opts, (res) => {
            let data = '';
            res.on('data', (c) => (data += c));
            res.on('end', () => {
                try { resolve(JSON.parse(data)); }
                catch { resolve({ _raw: data.slice(0, 200) }); }
            });
        });
        req.on('error', reject);
        if (body) req.write(body);
        req.end();
    });
}

// ─── 知识星球 API ────────────────────────────────────────

// 获取星球信息（自动命名）
async function fetchGroupInfo(groupId, cookie) {
    const ts = Math.floor(Date.now() / 1000).toString();
    const r = await httpReq({
        hostname: 'api.zsxq.com',
        path: `/v2/groups/${groupId}`,
        method: 'GET',
        headers: {
            'accept': 'application/json',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'referer': 'https://wx.zsxq.com/',
            'x-request-id': genUUID(),
            'x-signature': genSig(ts, ''),
            'x-timestamp': ts,
            'x-version': '2.89.0',
            'cookie': cookie
        }
    }, null);
    return r;
}

// Step 1: 获取图片上传 token
async function step1_getUploadToken(cookie, fileSize) {
    const ts = Math.floor(Date.now() / 1000).toString();
    const body = JSON.stringify({ req_data: { type: 'image', size: fileSize || 0, name: '', hash: '' } });
    const r = await httpReq({
        hostname: 'api.zsxq.com',
        path: '/v2/uploads',
        method: 'POST',
        headers: {
            'accept': 'application/json, text/plain, */*',
            'content-type': 'text/plain',
            'content-length': Buffer.byteLength(body),
            'origin': 'https://wx.zsxq.com',
            'referer': 'https://wx.zsxq.com/',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
            'x-aduid': genAduid(),
            'x-request-id': genUUID(),
            'x-signature': genSig(ts, body),
            'x-timestamp': ts,
            'x-version': '2.89.0',
            'cookie': cookie
        }
    }, body);
    return r?.succeeded ? r.resp_data?.upload_token : null;
}

// Step 2: 上传图片到七牛
async function step2_uploadToQiniu(uploadToken, fileBuffer, filename) {
    const boundary = '----WebKitFormBoundary' + Math.random().toString(36).slice(2);
    const CRLF = '\r\n';
    const mimeMap = { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', gif: 'image/gif', webp: 'image/webp' };
    const mime = mimeMap[filename.split('.').pop()] || 'image/jpeg';
    const basename = path.basename(filename);

    // 文件字段在前，token 在后（与浏览器行为一致）
    const header = `--${boundary}${CRLF}Content-Disposition: form-data; name="file"; filename="${basename}"${CRLF}Content-Type: ${mime}${CRLF}${CRLF}`;
    const footer = `${CRLF}--${boundary}${CRLF}Content-Disposition: form-data; name="token"${CRLF}${CRLF}${uploadToken}${CRLF}--${boundary}--${CRLF}`;

    const fullBody = Buffer.concat([
        Buffer.from(header, 'utf8'),
        fileBuffer,
        Buffer.from(footer, 'utf8')
    ]);

    const r = await httpReq({
        hostname: 'upload-z1.qiniup.com',
        path: '/',
        method: 'POST',
        headers: {
            'accept': 'application/json',
            'referer': 'https://wx.zsxq.com/',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'x-request-id': genUUID(),
            'x-version': '2.89.0',
            'content-type': `multipart/form-data; boundary=${boundary}`,
            'content-length': fullBody.length
        }
    }, fullBody);

    return r?.succeeded ? r.resp_data?.image_id : null;
}

// Step 3: 发帖
async function step3_postTopic(group, text, imageIds) {
    const ts = Math.floor(Date.now() / 1000).toString();
    const body = JSON.stringify({
        req_data: { type: 'topic', text, image_ids: imageIds || [], file_ids: [], mentioned_user_ids: [] }
    });
    return httpReq({
        hostname: 'api.zsxq.com',
        path: `/v2/groups/${group.groupId}/topics`,
        method: 'POST',
        headers: {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-CN,zh;q=0.9',
            'content-type': 'application/json',
            'content-length': Buffer.byteLength(body),
            'origin': 'https://wx.zsxq.com',
            'referer': 'https://wx.zsxq.com/',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
            'x-request-id': genUUID(),
            'x-signature': genSig(ts, body),
            'x-timestamp': ts,
            'x-version': '2.89.0',
            'x-aduid': genAduid(),
            'cookie': group.cookie
        }
    }, body);
}

// ─── 命令 ────────────────────────────────────────────────

async function cmdConfigAdd(args) {
    const { name, url, cookie } = args;
    if (!url || !cookie) { console.error('❌ 用法: node zsxq.js config add --url "..." --cookie "..." [--name "名称"]'); process.exit(1); }

    const groupId = extractGroupId(url);
    if (!groupId) { console.error('❌ URL 格式错误，示例：https://wx.zsxq.com/group/48885154455258'); process.exit(1); }

    let groupName = name;
    if (!groupName) {
        process.stdout.write('🔍 正在获取星球信息...');
        const info = await fetchGroupInfo(groupId, cookie);
        groupName = info?.succeeded && info?.resp_data?.group?.name
            ? (process.stdout.write(` ✓ ${info.resp_data.group.name}\n`), info.resp_data.group.name)
            : (console.log(` ⚠️  未能获取，使用默认名称`), `星球_${groupId}`);
    }

    const cfg = loadConfig();
    cfg.groups[groupName] = { groupId, cookie, url };
    if (!cfg.default) { cfg.default = groupName; console.log(`⭐ 已设为默认星球`); }
    saveConfig(cfg);
    ok(`已添加星球：${groupName}（ID: ${groupId}）`);
}

function cmdConfigList() {
    const cfg = loadConfig();
    const groups = Object.entries(cfg.groups);
    if (!groups.length) { console.log('📭 暂无配置的星球'); return; }
    console.log('📋 已配置的知识星球：\n');
    groups.forEach(([n, g]) => console.log(`  ${n === cfg.default ? '⭐' : '  '} ${n}  |  ID: ${g.groupId}`));
    console.log(`\n默认星球：${cfg.default || '未设置'}`);
}

function cmdConfigRemove(args) {
    const { name } = args;
    if (!name) { console.error('❌ 用法: node zsxq.js config remove --name "名称"'); process.exit(1); }
    const cfg = loadConfig();
    if (!cfg.groups[name]) { console.error(`❌ 未找到星球：${name}`); process.exit(1); }
    delete cfg.groups[name];
    if (cfg.default === name) {
        const rem = Object.keys(cfg.groups);
        cfg.default = rem[0] || null;
    }
    saveConfig(cfg);
    ok(`已移除：${name}`);
}

function cmdConfigDefault(args) {
    const { name } = args;
    if (!name) { console.error('❌ 用法: node zsxq.js config default --name "名称"'); process.exit(1); }
    const cfg = loadConfig();
    if (!cfg.groups[name]) { console.error(`❌ 未找到星球：${name}`); process.exit(1); }
    cfg.default = name;
    saveConfig(cfg);
    ok(`默认星球已设置为：${name}`);
}

async function cmdPost(args) {
    let { name, text, file, images } = args;

    if (file) {
        if (!fs.existsSync(file)) { console.error(`❌ 文件不存在：${file}`); process.exit(1); }
        text = fs.readFileSync(file, 'utf8').trim();
    }
    if (!text) {
        console.error('❌ 用法: node zsxq.js post --text "内容" [--name "星球"] [--images "a.jpg,b.png"]');
        console.error('       node zsxq.js post --file "/path.txt" [--images "a.jpg"]');
        process.exit(1);
    }

    const cfg = loadConfig();
    const target = name || cfg.default;
    if (!target) { console.error('❌ 未指定星球且无默认星球，请先添加：node zsxq.js config add ...'); process.exit(1); }
    const group = cfg.groups[target];
    if (!group) { console.error(`❌ 未找到星球：${target}`); process.exit(1); }

    inf(`发帖到：${target}（${group.groupId}）`);

    // ─── 图片处理 ───────────────────────────────────────
    let imageIds = [];
    if (images) {
        const paths = images.split(',').map((p) => p.trim()).filter(Boolean);
        if (paths.length > 9) { inf(`图片最多9张，已截断`); paths.length = 9; }
        inf(`上传 ${paths.length} 张图片...`);

        for (let i = 0; i < paths.length; i++) {
            const p = paths[i];
            if (!fs.existsSync(p)) { inf(`跳过不存在的文件：${p}`); continue; }

            process.stdout.write(`  [${i + 1}/${paths.length}] ${path.basename(p)} ... `);
            try {
                const buf = fs.readFileSync(p);
                const token = await step1_getUploadToken(group.cookie, buf.length);
                if (!token) { console.log('❌ 获取 upload_token 失败'); continue; }
                const id = await step2_uploadToQiniu(token, buf, p);
                if (!id) { console.log('❌ 上传失败'); continue; }
                imageIds.push(id);
                console.log(`✓ ${id}`);
            } catch (e) {
                console.log(`❌ ${e.message}`);
            }
        }
        ok(`图片处理完成（${imageIds.length}/${paths.length} 成功）`);
    }

    // ─── 发帖 ───────────────────────────────────────────
    inf('正在发帖...');
    const r = await step3_postTopic(group, text, imageIds);

    if (r.succeeded) {
        ok('发帖成功！');
        const tid = r.resp_data?.topic?.topic_id;
        if (tid) console.log(`${G}📌 帖子ID：${tid}${N}`);
        if (imageIds.length) console.log(`${G}📷 附带图片：${imageIds.length} 张${N}`);
    } else {
        console.error(`\n❌ 发帖失败 (code: ${r.code})`);
        console.error('响应:', JSON.stringify(r).slice(0, 300));
        
        // 提供具体的错误诊断
        if (r.code === 1004) {
            console.error(`\n💡 可能原因：`);
            console.error(`   1. Cookie 已过期，需要重新获取`);
            console.error(`   2. zsxq_access_token 无效或为空`);
            console.error(`\n📋 解决方法：`);
            console.error(`   1. 登录 https://wx.zsxq.com`);
            console.error(`   2. 按 F12 打开开发者工具 → Network`);
            console.error(`   3. 点击任意请求，复制完整的 Cookie 头值`);
            console.error(`   4. 运行: node zsxq.js config add --url "..." --cookie "新Cookie"`);
        }
        if (r.code === 1059) {
            console.error(`\n💡 可能原因：`);
            console.error(`   1. Cookie 权限不足`);
            console.error(`   2. 该账号被限制发帖`);
            console.error(`   3. Cookie 中的 token 已过期`);
        }
        process.exit(1);
    }
}

// ─── 入口 ────────────────────────────────────────────────
function parseArgs(argv) {
    const params = {};
    for (let i = 0; i < argv.length; i++) {
        if (argv[i].startsWith('--')) {
            let k = argv[i].slice(2);
            let v;
            if (k.includes('=')) {
                [k, ...v] = k.split('=');
                v = v.join('=');
            } else {
                v = argv[i + 1];
                if (v && !v.startsWith('--')) i++;
                else v = true;
            }
            params[k] = v;
        }
    }
    return params;
}

function showHelp() {
    console.log(`
知识星球 CLI v2.0 🦞

命令：
  config add      添加星球（自动获取名称）
  config list     查看已配置的星球
  config remove   移除星球
  config default  设置默认星球
  post            发帖（支持图片）

发帖选项：
  --text          帖子内容
  --file          从文件读取内容
  --images        图片路径，最多9张，逗号分隔
  --name          指定星球（不指定则用默认）

示例：
  node zsxq.js config add --url "https://wx.zsxq.com/group/ID" --cookie "..."
  node zsxq.js post --text "Hello" --images "/path/a.jpg,/path/b.png"
  node zsxq.js post --file "/tmp/post.txt" --images "/path/cover.png"

配置文件：~/.xfg-zsxq/groups.json
`);
}

async function main() {
    const args = process.argv.slice(2);
    const cmd = args[0];

    if (!cmd || cmd === '--help' || cmd === 'help') { showHelp(); return; }

    if (cmd === 'post') {
        await cmdPost(parseArgs(args.slice(1)));
    } else if (cmd === 'config') {
        const sub = args[1];
        const params = parseArgs(args.slice(2));
        if (sub === 'add')     await cmdConfigAdd(params);
        else if (sub === 'list')    cmdConfigList();
        else if (sub === 'remove')  cmdConfigRemove(params);
        else if (sub === 'default') cmdConfigDefault(params);
        else { console.error(`❌ 未知子命令: config ${sub}`); showHelp(); }
    } else {
        console.error(`❌ 未知命令: ${cmd}`);
        showHelp();
    }
}

main().catch(console.error);
