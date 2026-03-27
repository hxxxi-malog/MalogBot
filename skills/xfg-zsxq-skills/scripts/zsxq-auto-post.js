#!/usr/bin/env node

/**
 * 知识星球自动化发帖脚本
 * 使用 Node.js 内置模块，无需额外依赖
 * 
 * 原理：
 * 知识星球的签名算法通过分析前端 JS 得出：
 * x-timestamp = 当前 Unix 时间戳（秒）
 * x-signature = SHA1(x-timestamp + request_body_md5)
 * 
 * 使用方法:
 *   node zsxq-auto-post.js --cookie "YOUR_COOKIE" --text "帖子内容"
 */

const https = require('https');
const crypto = require('crypto');

// 解析命令行参数
function parseArgs() {
    const args = process.argv.slice(2);
    const params = {};
    for (let i = 0; i < args.length; i += 2) {
        const key = args[i].replace('--', '');
        params[key] = args[i + 1];
    }
    return params;
}

// 从 cookie 中提取 token
function extractToken(cookie) {
    const match = cookie.match(/zsxq_access_token=([^;]+)/);
    return match ? match[1].trim() : null;
}

// 生成签名
// 知识星球签名算法：SHA1(timestamp + MD5(body))
function generateSignature(timestamp, body) {
    const bodyMd5 = crypto.createHash('md5').update(body).digest('hex');
    const signStr = timestamp + bodyMd5;
    const signature = crypto.createHash('sha1').update(signStr).digest('hex');
    return signature;
}

// 生成 UUID
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// 发送 HTTP 请求
function sendRequest(options, body) {
    return new Promise((resolve, reject) => {
        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => data += chunk);
            res.on('end', () => {
                try {
                    resolve(JSON.parse(data));
                } catch (e) {
                    resolve({ raw: data });
                }
            });
        });
        req.on('error', reject);
        req.write(body);
        req.end();
    });
}

// 主函数
async function main() {
    const { cookie, text, group = '48885154455258' } = parseArgs();

    if (!cookie) {
        console.error('❌ 错误: 缺少 --cookie 参数');
        process.exit(1);
    }
    if (!text) {
        console.error('❌ 错误: 缺少 --text 参数');
        process.exit(1);
    }

    // 提取 token
    const token = extractToken(cookie);
    if (!token) {
        console.error('❌ 无法从 cookie 中提取 zsxq_access_token');
        process.exit(1);
    }
    console.log('✓ 已提取 access_token');

    // 构建请求体
    const body = JSON.stringify({
        req_data: {
            type: 'topic',
            text: text,
            image_ids: [],
            file_ids: [],
            mentioned_user_ids: []
        }
    });

    // 生成签名
    const timestamp = Math.floor(Date.now() / 1000).toString();
    const signature = generateSignature(timestamp, body);
    const requestId = generateUUID();

    console.log('✓ 已生成签名');
    console.log('🚀 正在发帖...');

    // 发送请求
    const options = {
        hostname: 'api.zsxq.com',
        path: `/v2/groups/${group}/topics`,
        method: 'POST',
        headers: {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-CN,zh;q=0.9',
            'cache-control': 'no-cache',
            'content-type': 'application/json',
            'content-length': Buffer.byteLength(body),
            'dnt': '1',
            'origin': 'https://wx.zsxq.com',
            'pragma': 'no-cache',
            'priority': 'u=1, i',
            'referer': 'https://wx.zsxq.com/',
            'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
            'x-request-id': requestId,
            'x-signature': signature,
            'x-timestamp': timestamp,
            'x-version': '2.89.0',
            'cookie': cookie
        }
    };

    const result = await sendRequest(options, body);

    if (result.succeeded) {
        console.log('✅ 发帖成功！');
        console.log(`📌 帖子ID: ${result.resp_data?.topic?.topic_id || '未知'}`);
    } else {
        console.error('❌ 发帖失败');
        console.error('响应:', JSON.stringify(result, null, 2));

        if (result.code === 401) {
            console.error('\n⚠️  Cookie 已过期，请重新获取：');
            console.error('  1. 访问 https://wx.zsxq.com');
            console.error('  2. 按 F12 → Network → 复制 Cookie');
        }
    }
}

main().catch(console.error);