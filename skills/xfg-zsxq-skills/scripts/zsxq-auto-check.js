#!/usr/bin/env node

/**
 * 知识星球自动检查通知脚本
 * 检查：新帖子、评论、被圈提醒
 * 
 * 使用方法:
 *   node zsxq-auto-check.js [--scope related|all] [--count 30]
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
    const params = { scope: 'all', count: 30 };
    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--scope' && args[i + 1]) params.scope = args[++i];
        if (args[i] === '--count' && args[i + 1]) params.count = parseInt(args[++i]);
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

// 格式化时间
function formatTime(timeStr) {
    const d = new Date(timeStr);
    const now = new Date();
    const diff = (now - d) / 1000;
    
    if (diff < 60) return '刚刚';
    if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
    return d.toLocaleString('zh-CN');
}

// 获取动态
async function fetchDynamics(cookie, scope, count) {
    const ts = Math.floor(Date.now() / 1000).toString();
    const beginTime = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    
    const headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9',
        'cookie': cookie,
        'origin': 'https://wx.zsxq.com',
        'referer': 'https://wx.zsxq.com/',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
        'x-request-id': generateUUID(),
        'x-signature': generateSignature(ts, ''),
        'x-timestamp': ts,
        'x-version': '2.89.0'
    };
    
    const path = `/v2/dynamics?scope=${scope}&count=${count}&begin_time=${encodeURIComponent(beginTime)}`;
    return httpReq('api.zsxq.com', path, 'GET', headers, null);
}

// 解析动态类型
function parseDynamicType(action) {
    const types = {
        'create_topic': { icon: '📝', name: '新帖子' },
        'create_comment': { icon: '💬', name: '新评论' },
        'create_reply': { icon: '🔁', name: '回复' },
        'mention': { icon: '👤', name: '被圈提醒' },
        'like': { icon: '❤️', name: '点赞' },
        'reward': { icon: '💰', name: '打赏' }
    };
    return types[action] || { icon: '📌', name: action };
}

// 解析文本（去除 HTML 标签）
function parseText(text) {
    return text
        .replace(/<e[^>]*\/>/g, '')
        .replace(/<[^>]+>/g, '')
        .replace(/&nbsp;/g, ' ')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .trim();
}

// 格式化输出
function formatOutput(dynamics, groupName) {
    if (!dynamics || !dynamics.resp_data || !dynamics.resp_data.dynamics) {
        return { mentions: [], posts: [], comments: [] };
    }
    
    const items = dynamics.resp_data.dynamics;
    const mentions = [];
    const posts = [];
    const comments = [];
    
    for (const item of items) {
        const type = parseDynamicType(item.action);
        const time = formatTime(item.create_time);
        
        // 获取内容
        let content = '';
        let owner = '';
        let targetOwner = '';
        let topicId = '';
        let topicOwner = '';
        
        if (item.topic) {
            topicId = item.topic.topic_id;
            if (item.topic.talk) {
                content = parseText(item.topic.talk.text);
                topicOwner = item.topic.talk.owner?.name || '未知';
            }
            if (item.topic.group) {
                groupName = item.topic.group.name || groupName;
            }
        }
        
        if (item.comment) {
            content = parseText(item.comment.text);
            owner = item.comment.owner?.name || '未知';
            if (item.topic?.talk) {
                targetOwner = item.topic.talk.owner?.name || '未知';
            }
        }
        
        // 提取被圈用户
        const mentionMatches = (item.comment?.text || '').match(/type="mention"[^>]*title="([^"]+)"/g) || [];
        const mentionedUsers = mentionMatches.map(m => {
            const match = m.match(/title="([^"]+)"/);
            return match ? decodeURIComponent(match[1].replace(/%/g, '%25')) : '';
        }).filter(Boolean);
        
        const record = {
            type,
            time,
            content: content.slice(0, 200),
            owner,
            targetOwner,
            topicOwner,
            topicId,
            groupName,
            mentionedUsers
        };
        
        // 判断是否被圈
        if (mentionedUsers.length > 0 || item.action === 'mention') {
            mentions.push(record);
        }
        
        // 分类
        if (item.action === 'create_topic') {
            posts.push(record);
        } else if (item.action === 'create_comment' || item.action === 'create_reply') {
            comments.push(record);
        }
    }
    
    return { mentions, posts, comments };
}

// 主函数
async function main() {
    console.log(`\n${B}═══════════════════════════════════════${N}`);
    console.log(`${B}  🦞 知识星球通知检查${N}`);
    console.log(`${B}═══════════════════════════════════════${N}\n`);
    
    const { scope, count } = parseArgs();
    const config = loadConfig();
    
    if (!config || !config.default || !config.groups[config.default]) {
        console.error(`${R}❌ 未配置知识星球${N}`);
        console.error(`   请先运行: node zsxq.js config add --url "..." --cookie "..."`);
        process.exit(1);
    }
    
    const group = config.groups[config.default];
    console.log(`${B}📍 星球: ${config.default}${N}`);
    console.log(`${B}🔍 范围: ${scope === 'related' ? '与我相关' : '全部'} | 数量: ${count}${N}\n`);
    
    try {
        // 获取动态
        process.stdout.write('⏳ 获取动态中... ');
        const result = await fetchDynamics(group.cookie, scope, count);
        
        if (!result.succeeded) {
            console.log(`${R}❌ 获取失败${N}`);
            console.error(result);
            process.exit(1);
        }
        console.log(`${G}✓${N}`);
        
        const { mentions, posts, comments } = formatOutput(result, config.default);
        
        // 输出结果
        if (mentions.length > 0) {
            console.log(`\n${Y}👤 被圈提醒 (${mentions.length} 条)${N}`);
            console.log('─'.repeat(50));
            for (const m of mentions) {
                console.log(`  ${m.type.icon} ${m.time} | ${m.owner}`);
                if (m.mentionedUsers.length > 0) {
                    console.log(`     被圈: ${m.mentionedUsers.join(', ')}`);
                }
                if (m.content) {
                    console.log(`     内容: ${m.content.slice(0, 100)}${m.content.length > 100 ? '...' : ''}`);
                }
                if (m.topicId) {
                    console.log(`     帖子: ${m.topicId}`);
                }
                console.log('');
            }
        } else {
            console.log(`\n${G}✅ 没有新的被圈提醒${N}`);
        }
        
        if (posts.length > 0) {
            console.log(`\n${B}📝 新帖子 (${posts.length} 条)${N}`);
            console.log('─'.repeat(50));
            for (const p of posts.slice(0, 5)) {
                console.log(`  📝 ${p.time} | ${p.topicOwner}`);
                console.log(`     ${p.content.slice(0, 80)}${p.content.length > 80 ? '...' : ''}`);
                console.log('');
            }
            if (posts.length > 5) console.log(`  ... 还有 ${posts.length - 5} 条`);
        }
        
        if (comments.length > 0) {
            console.log(`\n${B}💬 新评论 (${comments.length} 条)${N}`);
            console.log('─'.repeat(50));
            for (const c of comments.slice(0, 5)) {
                console.log(`  💬 ${c.time} | ${c.owner} → ${c.targetOwner}`);
                console.log(`     ${c.content.slice(0, 80)}${c.content.length > 80 ? '...' : ''}`);
                console.log('');
            }
            if (comments.length > 5) console.log(`  ... 还有 ${comments.length - 5} 条`);
        }
        
        console.log(`\n${B}═══════════════════════════════════════${N}`);
        console.log(`${B}  检查完成${N}`);
        console.log(`${B}═══════════════════════════════════════${N}\n`);
        
        // 返回结构化数据供程序使用
        return { mentions, posts, comments };
        
    } catch (e) {
        console.error(`${R}❌ 错误: ${e.message}${N}`);
        process.exit(1);
    }
}

main().then(result => {
    // 输出 JSON 格式供其他脚本使用
    if (process.env.OUTPUT_JSON === 'true') {
        console.log(JSON.stringify(result));
    }
}).catch(console.error);
