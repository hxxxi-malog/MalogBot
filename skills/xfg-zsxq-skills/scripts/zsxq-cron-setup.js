#!/usr/bin/env node

/**
 * 知识星球定时任务设置脚本
 * 设置 OpenClaw 定时任务自动检查通知
 * 
 * 使用方法:
 *   node zsxq-cron-setup.js [--interval 30] [--action check|post]
 */

const https = require('https');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const os = require('os');

// 配置文件
const CONFIG_FILE = path.join(os.homedir(), '.xfg-zsxq', 'groups.json');
const WORKSPACE_DIR = path.join(os.homedir(), '.qclaw', 'workspace');

// 颜色
const R = '\x1b[31m';
const G = '\x1b[32m';
const Y = '\x1b[33m';
const B = '\x1b[36m';
const N = '\x1b[0m';

// 解析命令行参数
function parseArgs() {
    const args = process.argv.slice(2);
    const params = { interval: 30, action: 'check' };
    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--interval' && args[i + 1]) params.interval = parseInt(args[++i]);
        if (args[i] === '--action' && args[i + 1]) params.action = args[++i];
        if (args[i] === '--stop') params.action = 'stop';
        if (args[i] === '--list') params.action = 'list';
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

// 输出颜色日志
function log(type, msg) {
    const colors = { ok: G, err: R, info: B, warn: Y };
    console.log(`${colors[type] || ''}${msg}${N}`);
}

// 生成定时任务配置
function generateCronJob(interval, groupName) {
    const messages = {
        check: `请执行知识星球通知检查：

1. 运行检查脚本获取最新动态
2. 如果有新的被圈提醒，整理后回复给我
3. 如果有用户提问，可以考虑自动回帖帮助
4. 检查完成后汇报结果

星球: ${groupName}`,
        digest: `请生成知识星球日报：

1. 运行 zsxq-auto-check.js 获取最新动态
2. 总结今日重要帖子和讨论
3. 整理被圈提醒和问题
4. 输出一份简短的星球动态摘要`
    };

    return {
        name: `知识星球-${groupName}-${interval}分钟检查`,
        schedule: {
            kind: "every",
            everyMs: interval * 60 * 1000
        },
        payload: {
            kind: "agentTurn",
            message: messages[interval > 120 ? 'digest' : 'check'],
            model: "default"
        },
        sessionTarget: "isolated",
        delivery: {
            mode: "announce"
        },
        enabled: true
    };
}

// 显示当前定时任务
async function showCurrentJobs() {
    console.log(`\n${B}═══════════════════════════════════════${N}`);
    console.log(`${B}  📅 知识星球定时任务${N}`);
    console.log(`${B}═══════════════════════════════════════${N}\n`);
    
    log('info', '使用 OpenClaw CLI 查看定时任务：');
    console.log('  openclaw cron list');
    console.log('');
    log('info', '或查看 HEARTBEAT.md 文件：');
    console.log(`  cat ${WORKSPACE_DIR}/HEARTBEAT.md`);
    console.log('');
}

// 主函数
async function main() {
    console.log(`\n${B}═══════════════════════════════════════${N}`);
    console.log(`${B}  🦞 知识星球定时任务设置${N}`);
    console.log(`${B}═══════════════════════════════════════${N}\n`);
    
    const { interval, action } = parseArgs();
    const config = loadConfig();
    
    if (!config || !config.default || !config.groups[config.default]) {
        log('err', '❌ 未配置知识星球');
        log('info', '请先运行: node zsxq.js config add --url "..." --cookie "..."');
        process.exit(1);
    }
    
    const groupName = config.default;
    const group = config.groups[config.default];
    
    console.log(`📍 星球: ${groupName}`);
    console.log(`📍 Group ID: ${group.groupId}\n`);
    
    if (action === 'list') {
        await showCurrentJobs();
        return;
    }
    
    if (action === 'stop') {
        console.log(`${Y}⚠️  要停止定时任务，请使用 OpenClaw CLI：${N}`);
        console.log('');
        console.log('  openclaw cron list    # 查看所有定时任务');
        console.log('  openclaw cron remove --id <job-id>  # 删除任务');
        console.log('');
        console.log('或者编辑 HEARTBEAT.md 清空任务列表');
        return;
    }
    
    // 生成任务配置
    const job = generateCronJob(interval, groupName);
    
    console.log(`${B}📋 定时任务配置：${N}`);
    console.log('');
    console.log(`  名称: ${job.name}`);
    console.log(`  间隔: 每 ${interval} 分钟`);
    console.log(`  模式: ${job.sessionTarget}`);
    console.log('');
    
    console.log(`${B}📝 Cron Job JSON：${N}`);
    console.log('─'.repeat(50));
    console.log(JSON.stringify(job, null, 2));
    console.log('─'.repeat(50));
    console.log('');
    
    console.log(`${Y}⚠️  OpenClaw 定时任务需要通过 CLI 设置${N}`);
    console.log('');
    console.log('请运行以下命令创建定时任务：');
    console.log('');
    console.log('  openclaw cron add \\');
    console.log('    --name "' + job.name + '" \\');
    console.log('    --every ' + (interval * 60 * 1000) + ' \\');
    console.log('    --target isolated \\');
    console.log('    --message "' + job.payload.message.replace(/\n/g, '\\n') + '"');
    console.log('');
    
    // 保存到配置文件
    const cronConfig = {
        lastUpdated: new Date().toISOString(),
        groupName,
        groupId: group.groupId,
        interval,
        job
    };
    
    const cronConfigFile = path.join(os.homedir(), '.xfg-zsxq', 'cron-config.json');
    const cronDir = path.dirname(cronConfigFile);
    
    if (!fs.existsSync(cronDir)) {
        fs.mkdirSync(cronDir, { recursive: true });
    }
    
    fs.writeFileSync(cronConfigFile, JSON.stringify(cronConfig, null, 2));
    log('ok', `✅ 定时任务配置已保存到 ${cronConfigFile}`);
    console.log('');
    log('info', '使用 --stop 参数可查看停止方法');
}

main().catch(console.error);
