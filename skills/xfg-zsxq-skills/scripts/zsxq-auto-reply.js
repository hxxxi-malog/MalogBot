#!/usr/bin/env node

/**
 * 知识星球自动回复脚本
 * 使用浏览器自动化方式回复帖子
 * 
 * 使用方法:
 *   node zsxq-auto-reply.js --topic-id <帖子ID> --text "回复内容"
 *   node zsxq-auto-reply.js --text "内容" --mention <用户ID>
 */

const https = require('https');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const os = require('os');

// 配置文件
const CONFIG_FILE = path.join(os.homedir(), '.xfg-zsxq', 'groups.json');

// 颜色
const R = '\x1b[31m';
const G = '\x1b[32m';
const Y = '\x1b[33m';
const B = '\x1b[36m';
const N = '\x1b[0m';

// 解析命令行参数
function parseArgs() {
    const args = process.argv.slice(2);
    const params = {};
    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--topic-id' && args[i + 1]) params.topicId = args[++i];
        if (args[i] === '--text' && args[i + 1]) params.text = args[++i];
        if (args[i] === '--mention' && args[i + 1]) params.mention = args[++i];
    }
    return params;
}

// 加载配置
function loadConfig() {
    try {
        if (fs.existsSync(CONFIG_FILE)) {
            return JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
        }
    } catch (e) {}
    return null;
}

// 生成签名
function generateSignature(timestamp, body) {
    const bodyMd5 = crypto.createHash('md5').update(body || '').digest('hex');
    return crypto.createHash('sha1').update(timestamp + bodyMd5).digest('hex');
}

// 生成 UUID
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = Math.random() * 16 | 0;
        return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    });
}

// 发送请求
function httpReq(hostname, path, method, headers, body) {
    return new Promise((resolve, reject) => {
        const opts = { hostname, path, method, headers };
        const req = https.request(opts, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => {
                try { resolve(JSON.parse(data)); }
                catch { resolve({ raw: data.slice(0, 200) }); }
            });
        });
        req.on('error', reject);
        if (body) req.write(body);
        req.end();
    });
}

// 获取帖子列表（用于找到帖子所在页面）
async function findTopicPage(topicId, cookie, groupId) {
    const ts = Math.floor(Date.now() / 1000).toString();
    
    // 尝试获取帖子详情
    const headers = {
        'accept': 'application/json',
        'cookie': cookie,
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'referer': 'https://wx.zsxq.com/',
        'x-request-id': generateUUID(),
        'x-signature': generateSignature(ts, ''),
        'x-timestamp': ts,
        'x-version': '2.89.0'
    };
    
    // 获取最新帖子列表
    const r = await httpReq('api.zsxq.com', `/v2/groups/${groupId}/topics?count=20`, 'GET', headers, null);
    
    if (!r.succeeded) {
        return null;
    }
    
    const topics = r.resp_data?.topics || [];
    const topic = topics.find(t => t.topic_id === topicId);
    
    if (topic) {
        return {
            groupId,
            ownerName: topic.talk?.owner?.name || '未知'
        };
    }
    
    return null;
}

// 检查是否需要浏览器自动化
async function needBrowserAutomation() {
    console.log(`\n${Y}⚠️  API 回复功能受限${N}`);
    console.log(`${Y}⚠️  请使用浏览器自动化方式回复${N}`);
    console.log(`\n步骤：`);
    console.log(`1. 在浏览器中打开星球页面`);
    console.log(`2. 找到帖子并点击"评论"按钮`);
    console.log(`3. 输入回复内容`);
    console.log(`4. 点击"评论"按钮发送`);
    console.log(`\n或者使用 OpenClaw 浏览器工具：`);
    console.log(`   browser action=snapshot target=host`);
    console.log(`   browser action=act target=host ref=<评论按钮> kind=click`);
    console.log(`   browser action=act target=host ref=<输入框> kind=type text="内容"`);
    console.log(`   browser action=act target=host ref=<发送按钮> kind=click`);
}

// 主函数
async function main() {
    console.log(`\n${B}═══════════════════════════════════════${N}`);
    console.log(`${B}  🦞 知识星球自动回复${N}`);
    console.log(`${B}═══════════════════════════════════════${N}\n`);
    
    const { topicId, text, mention } = parseArgs();
    const config = loadConfig();
    
    if (!config || !config.default || !config.groups[config.default]) {
        console.error(`${R}❌ 未配置知识星球${N}`);
        console.error(`   请先运行: node zsxq.js config add --url "..." --cookie "..."`);
        process.exit(1);
    }
    
    if (!text) {
        console.error(`${R}❌ 未指定回复内容${N}`);
        console.error(`   用法: node zsxq-auto-reply.js --topic-id <ID> --text "内容"`);
        process.exit(1);
    }
    
    const group = config.groups[config.default];
    console.log(`${B}📍 星球: ${config.default}${N}`);
    console.log(`${B}📝 内容: ${text}${N}\n`);
    
    // 构建回复内容
    let replyText = text;
    if (mention) {
        replyText = `@${mention} ${text}`;
    }
    
    // 尝试使用 API 回复
    try {
        const ts = Math.floor(Date.now() / 1000).toString();
        const body = JSON.stringify({
            req_data: {
                text: replyText,
                image_ids: [],
                mentioned_user_ids: mention ? [mention] : []
            }
        });
        
        const targetTopicId = topicId || 'latest';
        const headers = {
            'accept': 'application/json, text/plain, */*',
            'content-type': 'application/json',
            'content-length': Buffer.byteLength(body),
            'cookie': group.cookie,
            'origin': 'https://wx.zsxq.com',
            'referer': 'https://wx.zsxq.com/',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
            'x-request-id': generateUUID(),
            'x-signature': generateSignature(ts, body),
            'x-timestamp': ts,
            'x-version': '2.89.0'
        };
        
        console.log(`${B}⏳ 尝试 API 回复...${N}`);
        
        const r = await httpReq('api.zsxq.com', `/v2/topics/${targetTopicId}/comments`, 'POST', headers, body);
        
        if (r.succeeded) {
            console.log(`${G}✅ 回复成功！${N}`);
            console.log(`   评论ID: ${r.resp_data?.comment?.comment_id}`);
            return;
        }
        
        console.log(`${Y}⚠️  API 回复失败: ${r.error} (${r.code})${N}`);
        
    } catch (e) {
        console.log(`${Y}⚠️  API 请求失败: ${e.message}${N}`);
    }
    
    // 提示浏览器自动化
    await needBrowserAutomation();
    
    console.log(`\n${B}═══════════════════════════════════════${N}\n`);
}

main().catch(console.error);
