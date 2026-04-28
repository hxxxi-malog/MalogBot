"""
深度研究 API 接口

提供前端调用的 REST API，支持：
- 发起研究（标准/深度模式）
- 恢复研究（回答澄清问题）
- 取消研究
- 获取研究状态和计划
- 确认研究计划
- SSE 实时进度推送
- 历史研究列表
"""
import asyncio
import json
import logging
import time
from typing import Any, Optional

from flask import Blueprint, request, jsonify, Response, session
from pydantic import BaseModel, ValidationError, field_validator

from services.deep_research.research_service import (
    ResearchService,
    ResearchError,
    ResearchCancelledError,
    sse_gateway,
)
from services.deep_research.models import ResearchMode, ResearchStatus
from services.deep_research.events import SSEEventType
from services.deep_research.report_generator import ReportGenerator
from services.deep_research.pdf_exporter import PDFExporter

logger = logging.getLogger(__name__)

# 创建 Blueprint
research_bp = Blueprint('research', __name__, url_prefix='/api/research')

# 全局研究服务实例
_research_service: Optional[ResearchService] = None


def get_research_service() -> ResearchService:
    """获取研究服务单例"""
    global _research_service
    if _research_service is None:
        _research_service = ResearchService()
    return _research_service


def run_async(coro):
    """在同步上下文中运行异步函数"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def get_session_id() -> str:
    """获取或创建会话ID"""
    if 'session_id' not in session:
        session['session_id'] = str(__import__('uuid').uuid4())
    return session['session_id']


# ============ Pydantic 模型定义 ============

class StartResearchRequest(BaseModel):
    """发起研究请求"""
    query: str
    mode: str = "standard"

    @field_validator('query')
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('研究问题不能为空')
        return v.strip()

    @field_validator('mode')
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ('standard', 'deep'):
            raise ValueError('模式必须是 standard 或 deep')
        return v


class ResumeResearchRequest(BaseModel):
    """恢复研究请求"""
    answer: str

    @field_validator('answer')
    @classmethod
    def validate_answer(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('回答不能为空')
        return v.strip()


class UpdatePlanRequest(BaseModel):
    """更新研究计划请求"""
    directions: list[dict[str, Any]]

    @field_validator('directions')
    @classmethod
    def validate_directions(cls, v: list) -> list:
        if not v:
            raise ValueError('研究方向不能为空')
        for d in v:
            if not d.get('name'):
                raise ValueError('研究方向必须有名称')
        return v


# ============ API 接口实现 ============

@research_bp.route('/prepare', methods=['POST'])
def prepare_research():
    """
    准备研究任务（两阶段启动模式 - 第一阶段）
    
    创建研究任务但不启动异步执行。前端需要：
    1. 获取 task_id
    2. 建立 SSE 连接（GET /events/{task_id}）
    3. 调用 /start/{task_id} 启动执行
    
    这种设计确保 SSE 连接在异步任务执行前已建立，
    避免澄清消息在连接建立前推送导致丢失。

    Request Body:
        query: 研究问题（必填）
        mode: 研究模式 "standard" | "deep"（默认 standard）

    Returns:
        task_id: 任务ID
        status: 当前状态（PENDING）
        mode: 研究模式
    """
    try:
        # 验证请求
        data = request.json or {}
        try:
            req = StartResearchRequest(**data)
        except ValidationError as e:
            return jsonify({'error': str(e)}), 400

        session_id = get_session_id()
        service = get_research_service()

        # 确定研究模式
        mode = ResearchMode.DEEP if req.mode == "deep" else ResearchMode.STANDARD

        # 准备任务（不启动执行）
        task = run_async(service.prepare_task(
            query=req.query,
            mode=mode,
            session_id=session_id,
        ))

        logger.info(f"[Research API] Task prepared: {task.id}, mode={mode.value}, session={session_id}")

        return jsonify({
            'status': 'ok',
            'task_id': task.id,
            'task_status': task.status.value,
            'mode': task.mode.value,
            'message': '研究任务已创建，等待启动'
        })

    except Exception as e:
        logger.error(f"[Research API] Failed to prepare research: {e}", exc_info=True)
        return jsonify({'error': f'准备研究任务失败: {str(e)}'}), 500


@research_bp.route('/start/<task_id>', methods=['POST'])
def start_research_by_id(task_id: str):
    """
    启动研究任务执行（两阶段启动模式 - 第二阶段）
    
    在前端建立 SSE 连接后调用此接口启动异步任务执行。
    
    Args:
        task_id: 任务ID（由 /prepare 接口返回）

    Returns:
        task_id: 任务ID
        status: 当前状态
        mode: 研究模式
    """
    try:
        service = get_research_service()

        # 启动任务执行
        task = run_async(service.execute_task(task_id))

        logger.info(f"[Research API] Task started: {task_id}, mode={task.mode.value}")

        return jsonify({
            'status': 'ok',
            'task_id': task.id,
            'task_status': task.status.value,
            'mode': task.mode.value,
            'message': f'研究任务已启动，当前状态: {task.status.value}'
        })

    except ResearchError as e:
        logger.warning(f"[Research API] Start research error: {e}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"[Research API] Failed to start research: {e}", exc_info=True)
        return jsonify({'error': f'启动研究失败: {str(e)}'}), 500


@research_bp.route('/start', methods=['POST'])
def start_research():
    """
    发起新的研究任务（单阶段启动，向后兼容）

    Request Body:
        query: 研究问题（必填）
        mode: 研究模式 "standard" | "deep"（默认 standard）

    Returns:
        task_id: 任务ID
        status: 当前状态
        mode: 研究模式
        
    注意：此接口存在 SSE 时序竞争问题，推荐使用：
        1. POST /prepare
        2. GET /events/{task_id}
        3. POST /start/{task_id}
    """
    try:
        # 验证请求
        data = request.json or {}
        try:
            req = StartResearchRequest(**data)
        except ValidationError as e:
            return jsonify({'error': str(e)}), 400

        session_id = get_session_id()
        service = get_research_service()

        # 确定研究模式
        mode = ResearchMode.DEEP if req.mode == "deep" else ResearchMode.STANDARD

        # 发起研究
        task = run_async(service.start_research(
            query=req.query,
            mode=mode,
            session_id=session_id,
        ))

        logger.info(f"[Research API] Started research task {task.id}, mode={mode.value}")

        return jsonify({
            'status': 'ok',
            'task_id': task.id,
            'task_status': task.status.value,
            'mode': task.mode.value,
            'message': f'研究任务已创建，当前状态: {task.status.value}'
        })

    except Exception as e:
        logger.error(f"[Research API] Failed to start research: {e}", exc_info=True)
        return jsonify({'error': f'发起研究失败: {str(e)}'}), 500


@research_bp.route('/<task_id>/resume', methods=['POST'])
def resume_research(task_id: str):
    """
    恢复研究（回答澄清问题后）

    Args:
        task_id: 任务ID

    Request Body:
        answer: 用户回答

    Returns:
        task_id: 任务ID
        status: 当前状态
    """
    try:
        # 验证请求
        data = request.json or {}
        try:
            req = ResumeResearchRequest(**data)
        except ValidationError as e:
            return jsonify({'error': str(e)}), 400

        service = get_research_service()

        # 恢复研究
        task = run_async(service.resume_research(task_id, req.answer))

        logger.info(f"[Research API] Resumed research task {task_id}")

        return jsonify({
            'status': 'ok',
            'task_id': task.id,
            'task_status': task.status.value,
            'message': '研究已恢复'
        })

    except ResearchError as e:
        logger.warning(f"[Research API] Resume research error: {e}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"[Research API] Failed to resume research: {e}", exc_info=True)
        return jsonify({'error': f'恢复研究失败: {str(e)}'}), 500


@research_bp.route('/<task_id>/intervene', methods=['POST'])
def intervene_research(task_id: str):
    """
    发送干预消息

    在研究执行过程中，用户可以发送干预消息来引导研究方向。

    Args:
        task_id: 任务ID

    Request Body:
        message: 干预消息

    Returns:
        task_id: 任务ID
        status: 当前状态
    """
    try:
        # 验证请求
        data = request.json or {}
        message = data.get('message', '').strip()

        if not message:
            return jsonify({'error': '干预消息不能为空'}), 400

        service = get_research_service()

        # 添加干预消息
        task = run_async(service.add_intervention(task_id, message))

        logger.info(f"[Research API] Added intervention to task {task_id}")

        return jsonify({
            'status': 'ok',
            'task_id': task.id,
            'task_status': task.status.value,
            'message': '干预消息已接收'
        })

    except ResearchError as e:
        logger.warning(f"[Research API] Intervene research error: {e}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"[Research API] Failed to intervene research: {e}", exc_info=True)
        return jsonify({'error': f'发送干预消息失败: {str(e)}'}), 500


@research_bp.route('/<task_id>/cancel', methods=['POST'])
def cancel_research(task_id: str):
    """
    取消研究

    Args:
        task_id: 任务ID

    Returns:
        status: 状态
        message: 消息
    """
    try:
        service = get_research_service()
        success = run_async(service.cancel_research(task_id))

        if success:
            logger.info(f"[Research API] Cancelled research task {task_id}")
            return jsonify({
                'status': 'ok',
                'message': '研究已取消'
            })
        else:
            return jsonify({'error': '无法取消该研究任务'}), 400

    except Exception as e:
        logger.error(f"[Research API] Failed to cancel research: {e}", exc_info=True)
        return jsonify({'error': f'取消研究失败: {str(e)}'}), 500


@research_bp.route('/<task_id>/status', methods=['GET'])
def get_research_status(task_id: str):
    """
    获取研究状态

    Args:
        task_id: 任务ID

    Returns:
        task_id: 任务ID
        status: 当前状态
        progress: 进度信息
    """
    try:
        service = get_research_service()
        status = run_async(service.get_status(task_id))

        return jsonify({
            'status': 'ok',
            **status
        })

    except ResearchError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"[Research API] Failed to get status: {e}", exc_info=True)
        return jsonify({'error': f'获取状态失败: {str(e)}'}), 500


@research_bp.route('/<task_id>/plan', methods=['GET'])
def get_research_plan(task_id: str):
    """
    获取研究计划

    Args:
        task_id: 任务ID

    Returns:
        plan: 研究计划
    """
    try:
        service = get_research_service()
        plan = run_async(service.get_plan(task_id))

        if not plan:
            return jsonify({'error': '研究计划不存在'}), 404

        return jsonify({
            'status': 'ok',
            'plan': plan.to_dict()
        })

    except Exception as e:
        logger.error(f"[Research API] Failed to get plan: {e}", exc_info=True)
        return jsonify({'error': f'获取计划失败: {str(e)}'}), 500


@research_bp.route('/<task_id>/plan', methods=['PUT'])
def update_research_plan(task_id: str):
    """
    更新研究计划

    Args:
        task_id: 任务ID

    Request Body:
        directions: 研究方向列表

    Returns:
        plan: 更新后的计划
    """
    try:
        # 验证请求
        data = request.json or {}
        try:
            req = UpdatePlanRequest(**data)
        except ValidationError as e:
            return jsonify({'error': str(e)}), 400

        service = get_research_service()

        # 转换为 DirectionSpec
        from services.deep_research.models import DirectionSpec
        directions = [
            DirectionSpec(
                name=d.get('name', ''),
                description=d.get('description', ''),
                keywords=d.get('keywords', []),
                priority=d.get('priority', i+1),
            )
            for i, d in enumerate(req.directions)
        ]

        # 更新计划
        plan = run_async(service.update_plan(task_id, type('Plan', (), {
            'task_id': task_id,
            'directions': directions,
        })()))

        logger.info(f"[Research API] Updated plan for task {task_id}")

        return jsonify({
            'status': 'ok',
            'plan': plan.to_dict(),
            'message': '研究计划已更新'
        })

    except ResearchError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"[Research API] Failed to update plan: {e}", exc_info=True)
        return jsonify({'error': f'更新计划失败: {str(e)}'}), 500


@research_bp.route('/<task_id>/confirm', methods=['POST'])
def confirm_research_plan(task_id: str):
    """
    确认研究计划并开始执行

    Args:
        task_id: 任务ID

    Returns:
        task_id: 任务ID
        status: 当前状态
    """
    try:
        service = get_research_service()
        task = run_async(service.confirm_plan(task_id))

        logger.info(f"[Research API] Confirmed plan for task {task_id}")

        return jsonify({
            'status': 'ok',
            'task_id': task.id,
            'task_status': task.status.value,
            'message': '研究计划已确认，开始执行'
        })

    except ResearchError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"[Research API] Failed to confirm plan: {e}", exc_info=True)
        return jsonify({'error': f'确认计划失败: {str(e)}'}), 500


@research_bp.route('/<task_id>/events', methods=['GET'])
def research_events(task_id: str):
    """
    SSE 事件流接口

    推送研究进度的实时更新。

    Args:
        task_id: 任务ID

    Returns:
        SSE 流
    """
    session_id = get_session_id()

    def generate():
        """生成 SSE 事件流"""
        try:
            # 获取或创建事件队列
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                queue = loop.run_until_complete(sse_gateway.subscribe(session_id))
            except Exception as e:
                logger.error(f"[SSE] Failed to subscribe: {e}")
                yield f"event: error\ndata: {json.dumps({'error': '连接失败'})}\n\n"
                return

            logger.info(f"[SSE] Connection established for session {session_id}, task {task_id}")

            # 发送初始连接成功事件
            yield f"event: connected\ndata: {json.dumps({'task_id': task_id, 'message': 'SSE 连接已建立'})}\n\n"

            # 心跳计数器
            heartbeat_counter = 0

            while True:
                try:
                    # 等待消息，超时 15 秒发送心跳
                    try:
                        message = loop.run_until_complete(
                            asyncio.wait_for(queue.get(), timeout=15.0)
                        )
                    except asyncio.TimeoutError:
                        # 发送心跳
                        heartbeat_counter += 1
                        yield f": heartbeat {heartbeat_counter}\n\n"
                        continue

                    # 检查关闭信号
                    if message is None:
                        logger.info(f"[SSE] Received close signal for session {session_id}")
                        break

                    # 格式化消息为 SSE 格式
                    # message 可能是 dict 或已经格式化的字符串
                    if isinstance(message, dict):
                        event_type = message.get('event', 'message')
                        msg_data = json.dumps(message)
                        yield f"event: {event_type}\ndata: {msg_data}\n\n"
                    else:
                        yield message

                except Exception as e:
                    logger.error(f"[SSE] Error reading from queue: {e}")
                    break

        except GeneratorExit:
            logger.info(f"[SSE] Client disconnected for session {session_id}")
        except Exception as e:
            logger.error(f"[SSE] Error in SSE stream: {e}", exc_info=True)
        finally:
            sse_gateway.unsubscribe(session_id)
            logger.info(f"[SSE] Connection closed for session {session_id}")

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
            'Transfer-Encoding': 'chunked'
        }
    )


@research_bp.route('/history', methods=['GET'])
def get_research_history():
    """
    获取历史研究列表

    Query Parameters:
        limit: 返回数量限制（默认20）
        offset: 偏移量（默认0）

    Returns:
        researches: 研究列表
        total: 总数
    """
    try:
        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)
        session_id = request.args.get('session_id', None)

        # 查询数据库
        from models.research import ResearchTask as DBResearchTask
        from services.db_manager import db_manager

        db = db_manager.session_factory()
        try:
            query = db.query(DBResearchTask)

            # 按会话过滤
            if session_id:
                query = query.filter(DBResearchTask.session_id == session_id)

            # 排序和分页
            query = query.order_by(DBResearchTask.created_at.desc())
            total = query.count()
            tasks = query.offset(offset).limit(limit).all()

            researches = [
                {
                    'task_id': str(task.id),
                    'query': task.query,
                    'mode': task.mode,
                    'status': task.status,
                    'created_at': task.created_at.isoformat() if task.created_at else None,
                    'completed_at': task.completed_at.isoformat() if task.completed_at else None,
                }
                for task in tasks
            ]

            return jsonify({
                'status': 'ok',
                'researches': researches,
                'total': total,
                'limit': limit,
                'offset': offset
            })

        finally:
            db.close()

    except Exception as e:
        logger.error(f"[Research API] Failed to get history: {e}", exc_info=True)
        return jsonify({'error': f'获取历史记录失败: {str(e)}'}), 500


@research_bp.route('/<task_id>', methods=['GET'])
def get_research_detail(task_id: str):
    """
    获取研究详情

    Args:
        task_id: 任务ID

    Returns:
        task: 研究任务详情
        plan: 研究计划（如有）
        directions: 研究方向进度（如有）
    """
    try:
        from models.research import (
            ResearchTask as DBResearchTask,
            ResearchPlan as DBResearchPlan,
            ResearchDirection as DBResearchDirection,
        )
        from services.db_manager import db_manager

        db = db_manager.session_factory()
        try:
            # 获取任务
            task = db.query(DBResearchTask).filter(
                DBResearchTask.id == __import__('uuid').UUID(task_id)
            ).first()

            if not task:
                return jsonify({'error': '研究任务不存在'}), 404

            # 获取计划
            plan = db.query(DBResearchPlan).filter(
                DBResearchPlan.task_id == __import__('uuid').UUID(task_id)
            ).first()

            # 获取方向进度
            directions = db.query(DBResearchDirection).filter(
                DBResearchDirection.task_id == __import__('uuid').UUID(task_id)
            ).all()

            result = {
                'task': {
                    'task_id': str(task.id),
                    'session_id': task.session_id,
                    'query': task.query,
                    'mode': task.mode,
                    'status': task.status,
                    'current_step': task.current_step,
                    'error_message': task.error_message,
                    'created_at': task.created_at.isoformat() if task.created_at else None,
                    'started_at': task.started_at.isoformat() if task.started_at else None,
                    'completed_at': task.completed_at.isoformat() if task.completed_at else None,
                },
                'plan': None,
                'directions': []
            }

            if plan:
                result['plan'] = {
                    'plan_id': str(plan.id),
                    'directions': plan.directions,
                    'is_confirmed': plan.is_confirmed,
                }

            if directions:
                result['directions'] = [
                    {
                        'direction_id': d.direction_id,
                        'name': d.name,
                        'status': d.status,
                        'progress': d.progress,
                        'summary': d.summary,
                        'learnings_count': len(d.learnings) if d.learnings else 0,
                        'sources_count': len(d.sources) if d.sources else 0,
                    }
                    for d in directions
                ]

            return jsonify({
                'status': 'ok',
                **result
            })

        finally:
            db.close()

    except Exception as e:
        logger.error(f"[Research API] Failed to get detail: {e}", exc_info=True)
        return jsonify({'error': f'获取详情失败: {str(e)}'}), 500


@research_bp.route('/<task_id>/report', methods=['GET'])
def get_research_report(task_id: str):
    """
    获取研究报告内容

    Args:
        task_id: 任务ID

    Query Parameters:
        format: 返回格式 "markdown" | "html"（默认 markdown）

    Returns:
        report: 研究报告内容
    """
    try:
        from models.research import (
            ResearchTask as DBResearchTask,
            ResearchPlan as DBResearchPlan,
            ResearchDirection as DBResearchDirection,
            ResearchReport as DBResearchReport,
        )
        from services.db_manager import db_manager

        db = db_manager.session_factory()
        try:
            # 检查任务是否存在
            task = db.query(DBResearchTask).filter(
                DBResearchTask.id == __import__('uuid').UUID(task_id)
            ).first()

            if not task:
                return jsonify({'error': '研究任务不存在'}), 404

            # 检查任务状态
            if task.status != 'completed':
                return jsonify({'error': f'研究任务尚未完成，当前状态: {task.status}'}), 400

            # 获取报告
            report = db.query(DBResearchReport).filter(
                DBResearchReport.task_id == __import__('uuid').UUID(task_id)
            ).first()

            if not report:
                # 如果报告不存在，实时生成
                logger.info(f"[Research API] Generating report for task {task_id}")

                # 获取计划
                plan = db.query(DBResearchPlan).filter(
                    DBResearchPlan.task_id == __import__('uuid').UUID(task_id)
                ).first()

                # 获取方向
                directions = db.query(DBResearchDirection).filter(
                    DBResearchDirection.task_id == __import__('uuid').UUID(task_id)
                ).all()

                # 转换为内存模型
                from services.deep_research.models import (
                    ResearchTask as ResearchTaskModel,
                    ResearchPlan as ResearchPlanModel,
                    ResearchDirection as ResearchDirectionModel,
                )

                task_model = ResearchTaskModel(
                    id=str(task.id),
                    session_id=task.session_id,
                    query=task.query,
                    mode=ResearchMode(task.mode),
                    status=ResearchStatus(task.status),
                )

                plan_model = None
                if plan:
                    from services.deep_research.models import DirectionSpec
                    plan_model = ResearchPlanModel(
                        id=str(plan.id),
                        task_id=str(plan.task_id),
                        directions=[
                            DirectionSpec.from_dict(d)
                            for d in (plan.directions or [])
                        ],
                    )

                direction_models = []
                for d in directions:
                    from services.deep_research.models import Learning, Source
                    dir_model = ResearchDirectionModel(
                        id=str(d.id),
                        task_id=str(d.task_id),
                        direction_id=d.direction_id,
                        name=d.name,
                        status=d.status,
                        progress=d.progress,
                        summary=d.summary or "",
                    )
                    # 添加学习成果
                    if d.learnings:
                        for l_data in d.learnings:
                            dir_model.learnings.append(Learning.from_dict(l_data))
                    # 添加来源
                    if d.sources:
                        for s_data in d.sources:
                            dir_model.sources.append(Source.from_dict(s_data))
                    direction_models.append(dir_model)

                # 生成报告
                generator = ReportGenerator()
                markdown_content = generator.generate_markdown(
                    task_model,
                    plan_model,
                    direction_models,
                )

                # 保存到数据库
                report = DBResearchReport(
                    task_id=task.id,
                    title=f"研究报告：{task.query[:50]}",
                    content_markdown=markdown_content,
                    word_count=len(markdown_content),
                    source_count=sum(len(d.sources or []) for d in directions),
                )
                db.add(report)
                db.commit()
                db.refresh(report)

                logger.info(f"[Research API] Report generated and saved: {report.id}")

            # 返回报告
            format_type = request.args.get('format', 'markdown')

            if format_type == 'html' and report.content_html:
                content = report.content_html
            else:
                content = report.content_markdown

            return jsonify({
                'status': 'ok',
                'report': {
                    'id': str(report.id),
                    'task_id': str(report.task_id),
                    'title': report.title,
                    'content': content,
                    'word_count': report.word_count,
                    'source_count': report.source_count,
                    'created_at': report.created_at.isoformat() if report.created_at else None,
                }
            })

        finally:
            db.close()

    except Exception as e:
        logger.error(f"[Research API] Failed to get report: {e}", exc_info=True)
        return jsonify({'error': f'获取报告失败: {str(e)}'}), 500


@research_bp.route('/<task_id>/report/download', methods=['GET'])
def download_research_report(task_id: str):
    """
    下载研究报告

    Args:
        task_id: 任务ID

    Query Parameters:
        format: 下载格式 "markdown" | "pdf"（默认 pdf）

    Returns:
        文件下载
    """
    try:
        from models.research import (
            ResearchTask as DBResearchTask,
            ResearchReport as DBResearchReport,
        )
        from services.db_manager import db_manager
        from flask import send_file
        import io
        import tempfile

        db = db_manager.session_factory()
        try:
            # 检查任务
            task = db.query(DBResearchTask).filter(
                DBResearchTask.id == __import__('uuid').UUID(task_id)
            ).first()

            if not task:
                return jsonify({'error': '研究任务不存在'}), 404

            # 获取报告
            report = db.query(DBResearchReport).filter(
                DBResearchReport.task_id == __import__('uuid').UUID(task_id)
            ).first()

            if not report:
                return jsonify({'error': '报告尚未生成'}), 404

            # 获取格式参数
            format_type = request.args.get('format', 'pdf')

            # 生成文件名
            safe_title = "".join(c for c in report.title if c.isalnum() or c in (' ', '-', '_')).strip()
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            if format_type == 'pdf':
                # PDF 导出
                try:
                    exporter = PDFExporter()
                    pdf_bytes = exporter.export_pdf(
                        markdown_content=report.content_markdown,
                        title=report.title,
                    )

                    filename = f"{safe_title}_{timestamp}.pdf"

                    logger.info(f"[Research API] Downloading PDF report for task {task_id}")

                    return send_file(
                        io.BytesIO(pdf_bytes),
                        mimetype='application/pdf',
                        as_attachment=True,
                        download_name=filename,
                    )
                except RuntimeError as e:
                    # weasyprint 未安装，返回 Markdown
                    logger.warning(f"[Research API] PDF export failed: {e}, returning markdown")
                    format_type = 'markdown'
                except Exception as e:
                    logger.error(f"[Research API] PDF export error: {e}", exc_info=True)
                    return jsonify({'error': f'PDF 导出失败: {str(e)}'}), 500

            if format_type == 'markdown':
                # Markdown 导出
                filename = f"{safe_title}_{timestamp}.md"

                logger.info(f"[Research API] Downloading Markdown report for task {task_id}")

                return send_file(
                    io.BytesIO(report.content_markdown.encode('utf-8')),
                    mimetype='text/markdown',
                    as_attachment=True,
                    download_name=filename,
                )

            return jsonify({'error': f'不支持的格式: {format_type}'}), 400

        finally:
            db.close()

    except Exception as e:
        logger.error(f"[Research API] Failed to download report: {e}", exc_info=True)
        return jsonify({'error': f'下载报告失败: {str(e)}'}), 500


# 导出 Blueprint
__all__ = ['research_bp']
