/* python-cordis site · 双语切换
   用 data-i18n="key" 标记元素,key 形如 "nav.home" 或 "hero.title"
   用 data-i18n-html="key" 标记需要 innerHTML 的元素 */
(function () {
  const STORE_KEY = 'cordis-promo-lang';

  const I18N = {
    zh: {
      /* ─── nav / chrome ─── */
      'nav.home':    '首页',
      'nav.start':   '快速开始',
      'nav.concepts':'核心概念',
      'nav.arch':    '架构',
      'nav.dev':     '开发指南',
      'nav.cta':     'GitHub',

      /* ─── index: hero ─── */
      'hero.kicker':     'Python 框架内核 · v0.1.4 · MIT',
      'hero.credit':     '灵感源自 <a href="https://github.com/koishijs/koishi">cordis</a> 框架 · 同一种 "everything is a plugin" 的设计语言',
      'hero.title':      '一切都可热插拔,副作用完整撤销,依赖变化自动反应。',
      'hero.tag':        'python-cordis 是一个由插件驱动的 Python 框架内核。它不预设 agent、LLM、文件或网络,只给你把所有业务当作可替换的插件拼装起来的最干净的底座。',
      'hero.cta.primary':'30 秒跑起来 →',
      'hero.cta.ghost':  '查看架构',
      'hero.term.label': '最小可行示例 · main.py',

      /* ─── index: features ─── */
      'feat.kicker': '最大亮点',
      'feat.title':  '为什么开发者选择 python-cordis',
      'feat.tag':    '围绕论文《A Programming Paradigm for Spatiotemporal Composability》的三大机制,落地为可用的 Python 框架。',

      'feat.rv.title': '可逆效应',
      'feat.rv.desc':  'ctx.effect / register / set / on 都返回一个幂等 disposer;拆卸时逆序执行反向操作,卸载一个组件 = 完整撤销它的全部副作用。',
      'feat.rv.ref':   'paper §3.1',

      'feat.co.title': '反应式余效应',
      'feat.co.desc':  '组件在 inject 里声明依赖,ctx.use 挂载后 Fiber 自动 reconcile:依赖出现 → 激活,依赖消失 → 休眠,无需手写生命周期。',
      'feat.co.ref':   'paper §3.2',

      'feat.hot.title':'事务化热重载',
      'feat.hot.desc': 'Loader.hot_reload 重新执行模块,销毁旧 Fiber 起新 Fiber;失败则回滚到上一个可用版本,永远不留下半成品状态。',
      'feat.hot.ref':  'paper §4.2',

      'feat.meta.title':'零业务预设',
      'feat.meta.desc':'不知道 agent、不绑 LLM、不接触文件系统。任何领域(agent 循环、Web 传输、ETL、游戏后端)都是平等的可替换插件。',
      'feat.meta.ref': 'meta-framework',

      'feat.hook.title':'四种调用模式',
      'feat.hook.desc':'HookRegistry 在 pluggy 之上加了四种 hook 调用模式:emit / parallel / bail / waterfall,覆盖大多数插件协作场景。',
      'feat.hook.ref': 'core/hook.py',

      'feat.obs.title':'可插拔可观测性',
      'feat.obs.desc':'fiber_started / fiber_stopped 是普通 hookspec,生命周期日志只是一个普通可逆插件 — 内核永不输出特权日志。',
      'feat.obs.ref':  'observability.py',

      /* ─── index: why cards ─── */
      'why.kicker':  '设计意图',
      'why.title':   '为什么不做成一个 agent 框架',
      'why.tag':     'agent 是上层应用的选择,不是内核的赌注。',

      'why.c1.title': '<span class="pill ok">机制层</span> 不绑死领域',
      'why.c1.desc':  '论文的两大原语(可逆效应 / 反应式余效应)落到 <code class="inline">Context</code> + <code class="inline">Fiber</code> 两个对象上;agent、LLM、Web 都是上层插件,内核对它们一无所知。',

      'why.c2.title': '<span class="pill warn">工具层</span> 不绑死运行时',
      'why.c2.desc':  '同步 / 异步 / 线程池 / 进程池 都是 <code class="inline">ctx.runner</code> 的一种实现,切换不需要重写组件。',

      'why.c3.title': '<span class="pill">生态层</span> 不绑死交付',
      'why.c3.desc':  '<code class="inline">python-cordis</code> 只发布 kernel;<code class="inline">python-cordis-agent</code> 提供可选的"全家桶插件",应用按需引入。',

      /* ─── index: companion ─── */
      'comp.kicker':  'Companion',
      'comp.title':   '可选的"全家桶"',
      'comp.banner.h': 'python-cordis-agent',
      'comp.banner.p': '应用层的现成插件集:agent 循环、LLM seam、会话日志、持久化后端、Web 传输。全部都是可替换的普通插件。',
      'comp.banner.a': '在 PyPI 查看 →',

      /* ─── quickstart ─── */
      'quick.kicker':   '30 秒跑起来',
      'quick.title':    '五个步骤,从 pip 到 fiber.stop()。',
      'quick.tag':      '先看完整链路,再去看每个细节。',

      'quick.s1.title': '安装 <span class="pill">Python ≥ 3.10</span>',
      'quick.s1.desc':  '核心包只依赖 <code class="inline">pluggy</code> 和 <code class="inline">omegaconf</code>,无原生扩展;可选 <code class="inline">watchdog</code> 提供文件监听。',

      'quick.s2.title': '定义 seam — 内核与插件唯一的耦合点',
      'quick.s2.desc':  '用 <code class="inline">@hookspec</code> 声明扩展点。内核与插件从此只通过 hookspec 对话,内核不知道任何具体插件。',

      'quick.s3.title': '写一个插件 — <code class="inline">inject</code> + <code class="inline">apply</code>',
      'quick.s3.desc':  '插件只需要两个东西:声明依赖的 <code class="inline">inject</code> 元组,和应用副作用的 <code class="inline">apply(ctx, ...)</code> 函数。<code class="inline">ctx.on</code> 注册监听,<code class="inline">ctx.effect</code> 记录拆卸操作 — 都是可逆的。',

      'quick.s4.title': '挂上一个 Fiber — 依赖满足即激活',
      'quick.s4.desc':  '把插件挂在 context 上,<code class="inline">ctx.use</code> 会自动 reconcile:<code class="inline">inject</code> 满足 → 立即激活;不满足 → 静默待命,直到依赖出现。',

      'quick.s5.title': '触发 & 拆卸 — 副作用完整撤销',
      'quick.s5.desc':  '触发 hook,组件按需响应。停止 fiber 时,所有 <code class="inline">effect</code>/<code class="inline">on</code>/<code class="inline">register</code> 的 disposer 按相反顺序执行,无残留。',

      'quick.s6.title': 'Bonus — 反应式余效应实战',
      'quick.s6.desc':  '下面这段直接展示"依赖消失 → 组件自动休眠":把 <code class="inline">register</code> 返回的 disposer 调用一下,Fiber 会把 Printer 拆掉;再注册,自动重建。',

      'quick.out.label':    '期望输出',
      'quick.cta.next.c':   '→ 核心概念',
      'quick.cta.next.a':   '→ 架构',

      /* ─── concepts ─── */
      'conc.h1': '五个积木,一个可组合内核。',
      'conc.tag': '围绕论文 <em>A Programming Paradigm for Spatiotemporal Composability</em> 的两大原语 —— <strong style="color:var(--accent)">可逆效应</strong> 与 <strong style="color:var(--accent)">反应式余效应</strong> —— 落地为五个核心抽象。',

      'conc.rv.kicker': '§3.1',
      'conc.rv.h2':     'Revertible Effects · 可逆效应',
      'conc.rv.desc':   '每一次对 context 的修改都返回一个幂等 disposer,拆卸时按相反顺序执行反向操作。卸载组件 = 完整撤销它的全部副作用。',
      'conc.rv.th.meaning': '含义',
      'conc.rv.th.returns': '返回',
      'conc.rv.t1.api':     '<code>ctx.register(name, value)</code>',
      'conc.rv.t1.desc':    '绑定一个具名服务',
      'conc.rv.t1.ret':     '<code class="inline">dispose</code>',
      'conc.rv.t2.api':     '<code>ctx.set(name, value)</code>',
      'conc.rv.t2.desc':    '同 register,并通知依赖它的 fiber',
      'conc.rv.t2.ret':     '<code class="inline">dispose</code>',
      'conc.rv.t3.api':     '<code>ctx.effect(fn)</code>',
      'conc.rv.t3.desc':    '记录一段拆卸操作',
      'conc.rv.t3.ret':     '<code class="inline">dispose</code>',
      'conc.rv.t4.api':     '<code>ctx.on(hooks, name, fn)</code>',
      'conc.rv.t4.desc':    '注册一个 hookimpl 监听',
      'conc.rv.t4.ret':     '<code class="inline">dispose</code>',
      'conc.rv.tail':       '这就是为什么 <code class="inline">fiber.stop()</code> 可以反复调用,也可以在异常路径上安全调用 —— 不会有"二次拆卸"导致的脏状态。',

      'conc.co.kicker':  '§3.2',
      'conc.co.h2':      'Reactive Coeffects · 反应式余效应',
      'conc.co.desc':    '组件在 <code class="inline">inject</code> 里声明它"需要什么",Fiber 会根据依赖的实际可用性自动 reconcile。',
      'conc.co.th.state':'状态',
      'conc.co.th.cond': '触发条件',
      'conc.co.th.side': '副作用',
      'conc.co.t1.state':'ACTIVE',
      'conc.co.t1.cond': '<code>inject</code> 全部满足',
      'conc.co.t1.side': '<code>apply()</code> 跑过,副作用已注册',
      'conc.co.t2.state':'INACTIVE',
      'conc.co.t2.cond': '<code>inject</code> 缺失',
      'conc.co.t2.side': '未激活,或已拆卸',
      'conc.co.t3.state':'APPLYING',
      'conc.co.t3.cond': '正在跑 <code>apply</code>',
      'conc.co.t3.side': '锁,防重入',
      'conc.co.kw':      '关键不变式:',
      'conc.co.li1':     '<strong style="color:var(--text)">单向:</strong> 注册 / 注销服务时,所有声明过该依赖的 fiber 都会被通知。',
      'conc.co.li2':     '<strong style="color:var(--text)">惰性:</strong> 依赖满足时立即激活;依赖消失时立即拆卸 — 不需要手写 watcher。',
      'conc.co.li3':     '<strong style="color:var(--text)">epoch:</strong> 每个 <code>refresh()</code> 轮次自增 <code>epoch</code>;陈旧通知被丢弃。',
      'conc.co.li4':     '<strong style="color:var(--text)">惯性:</strong> re-entrant 通知折叠到下一轮,避免栈溢出。',

      'conc.ctx.kicker': '§3.4',
      'conc.ctx.h2':     'Context · 反射式服务容器',
      'conc.ctx.desc':   'Context 既是服务仓库,也是效应边界。它实现论文的 <em>context paradigm</em>:每次变更被记录、可撤销,每次依赖变更被广播给声明它的 fiber。',
      'conc.ctx.cap1':   '# 反射式查找 + 父链',
      'conc.ctx.l1':     '# 在 root 注册',
      'conc.ctx.l2':     '# scope 子 context',
      'conc.ctx.l3':     '# 沿父链找到 root.fs',
      'conc.ctx.l4':     '# 论文的隔离 realm',
      'conc.ctx.l5':     '# shadow 父级同名服务',
      'conc.ctx.tail':   '<code class="inline">ctx.use(component)</code> 会创建一个 child context,并把访问权限限制在组件的 <code class="inline">inject</code> 声明之内 —— 这就是论文的 <em>proxy-mediated enforcement</em>:未声明的访问抛 <code class="inline">ServiceNotFound</code>。',

      'conc.fb.kicker': '§3.3',
      'conc.fb.h2':     'Fiber · 组件运行时实例',
      'conc.fb.desc':   'Fiber 是 component 的运行时包装:它把一个组件 spec(<code>inject</code> + <code>apply</code>) 绑定到一个 context,并拥有自己的生命周期。',
      'conc.fb.th.api': '方法',
      'conc.fb.th.sem': '语义',
      'conc.fb.t1.api': '<code>fiber.start()</code>',
      'conc.fb.t1.desc':'手动激活(若依赖不满足则抛错)',
      'conc.fb.t2.api': '<code>fiber.stop()</code>',
      'conc.fb.t2.desc':'手动拆卸,逆序执行所有 disposer',
      'conc.fb.t3.api': '<code>fiber.refresh()</code>',
      'conc.fb.t3.desc':'反应式 reconcile,依赖变更自动触发',
      'conc.fb.t4.api': '<code>fiber.dispose()</code>',
      'conc.fb.t4.desc':'永久卸载,无法再激活',

      'conc.hook.kicker':  'core/hook.py',
      'conc.hook.h2':      'Four hook modes · 四种调用模式',
      'conc.hook.desc':    '<code class="inline">HookRegistry</code> 在 pluggy 之上加了四种调用模式,覆盖大多数插件协作场景。',
      'conc.hook.th.mode': '模式',
      'conc.hook.th.beh':  '行为',
      'conc.hook.th.use':  '典型用途',
      'conc.hook.t1.mode': '<code>emit(name, **kw)</code>',
      'conc.hook.t1.beh':  '每个监听者都被调用,所有结果返回',
      'conc.hook.t1.use':  '事件广播、metrics 收集',
      'conc.hook.t2.mode': '<code>parallel(name, **kw)</code>',
      'conc.hook.t2.beh':  '线程池并发调用所有监听者',
      'conc.hook.t2.use':  '并行副作用、fan-out',
      'conc.hook.t3.mode': '<code>bail(name, **kw)</code>',
      'conc.hook.t3.beh':  '首个非 None 返回短路(<code>firstresult=True</code>)',
      'conc.hook.t3.use':  'provider 链、解析器',
      'conc.hook.t4.mode': '<code>waterfall(name, **kw)</code>',
      'conc.hook.t4.beh':  '链式委托,每层可选调用 <code>next</code>',
      'conc.hook.t4.use':  '中间件管道、命令链',
      'conc.hook.cap1':    '# → 用 bail 模式',
      'conc.hook.cap2':    '# → 用 waterfall 模式',
      'conc.cta.arch':     '→ 架构',
      'conc.cta.dev':      '→ 开发',

      /* ─── architecture ─── */
      'arch.h1':  '六个模块。三层。一个内核。',
      'arch.tag': '内核只提供 6 个模块、3 个抽象层。具体的 agent 循环、LLM seam、会话日志、持久化、Web 传输 —— 都是上一层"应用层"的普通可替换插件,内核对它们一无所知。',

      'arch.f6.kicker':  '六个模块',
      'arch.f6.h2':      'F1 — F6 · 六个核心模块',
      'arch.f6.desc':    '每个模块只做一件事,组合起来就是完整的插件化运行时。',
      'arch.f6.th.mod':  '模块',
      'arch.f6.th.dut':  '职责',
      'arch.f6.t1.num':  '<code>F1</code>',
      'arch.f6.t1.mod':  '<code>core/hook.py</code> · <code>HookRegistry</code>',
      'arch.f6.t1.dut':  'pluggy 之上的四种 hook 调用模式',
      'arch.f6.t2.num':  '<code>F2</code>',
      'arch.f6.t2.mod':  '<code>core/context.py</code> · <code>Context</code>',
      'arch.f6.t2.dut':  '反射式服务容器,scope chain,可逆效应',
      'arch.f6.t3.num':  '<code>F3</code>',
      'arch.f6.t3.mod':  '<code>core/fiber.py</code> · <code>Fiber</code>',
      'arch.f6.t3.dut':  '组件运行时实例,生命周期 + 反应式 reconcile',
      'arch.f6.t4.num':  '<code>F4</code>',
      'arch.f6.t4.mod':  '<code>core/config.py</code>',
      'arch.f6.t4.dut':  'OmegaConf 加载/覆盖/插值,无代码执行',
      'arch.f6.t5.num':  '<code>F5</code>',
      'arch.f6.t5.mod':  '<code>core/loader.py</code> · <code>Loader</code>',
      'arch.f6.t5.dut':  '声明式组件加载,<code>reconcile</code> + <code>hot_reload</code>',
      'arch.f6.t6.num':  '<code>F6</code>',
      'arch.f6.t6.mod':  '<code>core/hmr.py</code> · <code>Reloader</code>',
      'arch.f6.t6.dut':  '事务化热重载,失败回滚',

      'arch.layer.kicker': '分层架构',
      'arch.layer.h2':     '三层:内核 ↔ 扩展插件 ↔ 应用',
      'arch.layer.desc':   '箭头方向是依赖关系:上层依赖下层,下层不知道上层的存在。绿色边框 = 内核模块;橙色 = 应用层插件。',
      'arch.layer.l3.tag': 'Layer 3 · Application',
      'arch.layer.l3.h4':  '你的业务 <code class="inline">main.py</code>',
      'arch.layer.l3.desc':'把若干 entry 列表丢给 <code class="inline">Loader.reconcile</code>,业务就跑起来了。换业务不需要改内核。',
      'arch.layer.l2.tag': 'Layer 2 · Companion plugins',
      'arch.layer.l2.h4':  '<code>python-cordis-agent</code> · LLM / web / persistence · …',
      'arch.layer.l2.desc':'应用层的"现成插件集":agent 循环、LLM seam、会话日志、持久化后端、Web 传输,均为可替换插件。',
      'arch.layer.l1.tag': 'Layer 1 · Kernel',
      'arch.layer.l1.h4':  '<code>python-cordis</code> · HookRegistry / Context / Fiber / Loader / HMR',
      'arch.layer.l1.desc':'6 个模块,约 1500 行 Python。零业务预设,只提供"让插件可组合"的最低限度机制。',

      'arch.pe.kicker':  '插件发现',
      'arch.pe.h2':      '插件入口点约定',
      'arch.pe.desc':    'python-cordis 自己不声明任何入口点插件;应用通过标准 <code class="inline">python_cordis.plugins</code> group 注册自己的插件。',
      'arch.pe.cap1':    '# your-plugin/pyproject.toml',
      'arch.pe.cap2':    '# your app',
      'arch.pe.app':     '# 自动发现所有注册的插件',
      'arch.cta.dev':    '→ 开发',

      /* ─── dev ─── */
      'devs.h1':  '贡献、测试、发版。',
      'devs.tag': 'python-cordis 是 MIT 开源、strict mypy、单测覆盖六大模块。下面是从拉源码到发版的完整链路。',

      'devs.setup.kicker': '1 · Setup',
      'devs.setup.h2':     '本地开发环境',
      'devs.setup.desc':   '克隆后可编辑模式安装,自带 dev / hmr 额外依赖。',
      'devs.setup.tip':    '<code class="inline">dev</code> extra 提供 <code class="inline">pytest</code> / <code class="inline">pytest-cov</code> / <code class="inline">mypy</code> / <code class="inline">build</code>;<code class="inline">hmr</code> extra 提供 <code class="inline">watchdog</code>(可选)。',

      'devs.verify.kicker': '2 · Verify',
      'devs.verify.h2':     '测试、类型检查、打包',
      'devs.verify.desc':   '三件事一行命令;CI 也跑同一组。',
      'devs.verify.th.cmd': '命令',
      'devs.verify.th.eff': '作用',
      'devs.verify.t1.cmd': '<code>python -m mypy</code>',
      'devs.verify.t1.desc':'strict 模式类型检查(<code class="inline">pyproject.toml [tool.mypy]</code>)',
      'devs.verify.t2.cmd': '<code>python -m pytest</code>',
      'devs.verify.t2.desc':'运行测试套件(<code class="inline">tests/</code>)',
      'devs.verify.t3.cmd': '<code>python -m build</code>',
      'devs.verify.t3.desc':'同时产出 sdist + wheel',
      'devs.verify.cap':    '# 一次性跑完整套验证',

      'devs.author.kicker': '3 · Author',
      'devs.author.h2':     '写你自己的插件',
      'devs.author.desc':   '插件就是一对 <code class="inline">inject</code> + <code class="inline">apply</code>。下面是 minimum viable plugin 的完整形态。',
      'devs.author.tail':   '想看更多范例?<a href="concepts.html">核心概念页</a> 讲清了可逆效应 / 反应式余效应 / Context / Fiber / 四种 hook 模式,<a href="quickstart.html">快速开始</a> 有完整可跑通的 5 分钟示例。',

      'devs.ship.kicker': '4 · Ship',
      'devs.ship.h2':     '发版与贡献',
      'devs.ship.desc':   '本项目遵循 Conventional Commits;版本号手动维护于 <code class="inline">pyproject.toml</code>。',
      'devs.ship.c1.h':   'TestPyPI 验证',
      'devs.ship.c1.desc':'<code class="inline">python -m build</code> + <code class="inline">twine upload --repository testpypi dist/*</code> 先在测试环境试一遍,避免污染正式索引。',
      'devs.ship.c2.h':   '正式发版',
      'devs.ship.c2.desc':'改 <code class="inline">pyproject.toml</code> 中的 <code class="inline">version</code> + 同步 <code class="inline">__version__</code>,打 tag 推 <code class="inline">twine upload dist/*</code>。',
      'devs.ship.c3.h':   '提 PR',
      'devs.ship.c3.desc':'fork → feature branch → commit → PR。CI 会跑 mypy + pytest,需要保持 strict 模式干净。',
      'devs.ship.tail':   '详细贡献指南见 <a href="https://github.com/peroxider/python-cordis">GitHub repo</a>。License: <code class="inline">MIT</code> · Python ≥ 3.10。',
      'devs.cta.home':    '← 首页',
      'devs.cta.gh':      'GitHub →',

      /* ─── footer ─── */
      'foot.tag': '用 Python 写,为 Python 生态写。',
      'foot.lic': 'MIT License',

      /* ─── code-block comments ─── */
      'code.hero.c1':  "# inject=('config',) 已满足",
      'code.hero.c2':  '# Printer.apply 注册了 hookimpl',
      'code.hero.c3':  '拆卸逆序执行,副作用完整撤销',
      'code.qs3.c1':   '# 反应式余效应:依赖满足才激活',
      'code.qs4.c1':   '# True: 依赖已满足',
      'code.qs5.c1':   '# printer torn down   ← 自动调用 ctx.effect 注册的 lambda',
      'code.qs6.c1':   '# 撤销服务 → refresh 触发,fiber 自动 stop()',
      'code.qs6.c2':   '# True — 自动恢复',
      'code.crv.c1':   '# 调用一次后 armed = False,再次调用是 no-op',
      'code.crv.c2':   '# 拆',
      'code.crv.c3':   '# 安全 — 幂等',
      'code.arch.c1':  '# 一次最简单的"启动应用"',
      'code.arch.c2':  '# 增量 reconcile',
      'code.arch.c3':  '# 改文件 → 自动重载,失败回滚',
      'code.dev.c1':   '# 不需要任何依赖 → 立即激活',
      'code.dev.c2':   '# 可逆拆卸',
    },

    en: {
      /* ─── nav / chrome ─── */
      'nav.home':    'Home',
      'nav.start':   'Quick Start',
      'nav.concepts':'Concepts',
      'nav.arch':    'Architecture',
      'nav.dev':     'Develop',
      'nav.cta':     'GitHub',

      /* ─── index: hero ─── */
      'hero.kicker':      'Python framework kernel · v0.1.4 · MIT',
      'hero.credit':      'Inspired by <a href="https://github.com/koishijs/koishi">cordis</a> framework · the same "everything is a plugin" design language',
      'hero.title':       'Everything is a plugin. Side effects roll back. Dependencies react.',
      'hero.tag':         'python-cordis is a plugin-driven framework kernel for Python. It carries no opinions about agents, LLMs, files, or networks — it gives you the cleanest substrate to assemble any application from replaceable plugins.',
      'hero.cta.primary': 'Run in 30 seconds →',
      'hero.cta.ghost':   'See architecture',
      'hero.term.label':  'Minimal example · main.py',

      /* ─── index: features ─── */
      'feat.kicker': 'Highlights',
      'feat.title':  'Why developers choose python-cordis',
      'feat.tag':    'Three primitives from the paper "A Programming Paradigm for Spatiotemporal Composability", landed as a usable Python framework.',

      'feat.rv.title': 'Revertible Effects',
      'feat.rv.desc':  'ctx.effect / register / set / on all return idempotent disposers; teardown runs disposers in reverse order, so unloading a component = fully reverting all its side effects.',
      'feat.rv.ref':   'paper §3.1',

      'feat.co.title': 'Reactive Coeffects',
      'feat.co.desc':  'Components declare deps in inject; Fiber auto-reconciles after ctx.use — dependency appears → activate, disappears → sleep, no manual lifecycle.',
      'feat.co.ref':   'paper §3.2',

      'feat.hot.title':'Transactional hot reload',
      'feat.hot.desc': 'Loader.hot_reload re-executes the module, tears down the old Fiber and spins up a new one; on failure it rolls back to the last known-good version, never leaving a half-built state.',
      'feat.hot.ref':  'paper §4.2',

      'feat.meta.title':'Zero business opinions',
      'feat.meta.desc':'No agent baked in, no LLM coupling, no filesystem reach-in. Any domain (agent loop, web transport, ETL, game backend) is an equal-footing replaceable plugin.',
      'feat.meta.ref': 'meta-framework',

      'feat.hook.title':'Four hook modes',
      'feat.hook.desc':'HookRegistry adds four hook call modes on top of pluggy: emit / parallel / bail / waterfall, covering most plugin collaboration scenarios.',
      'feat.hook.ref': 'core/hook.py',

      'feat.obs.title':'Pluggable observability',
      'feat.obs.desc':'fiber_started / fiber_stopped are ordinary hookspecs; the lifecycle logger is just an ordinary revertible plugin — the kernel never emits privileged logs.',
      'feat.obs.ref':  'observability.py',

      /* ─── index: why cards ─── */
      'why.kicker':  'Design intent',
      'why.title':   'Why this is not an agent framework',
      'why.tag':     'Agent is an application-layer choice, not a kernel bet.',

      'why.c1.title': '<span class="pill ok">Mechanism</span> No domain lock-in',
      'why.c1.desc':  'The two primitives (revertible effects / reactive coeffects) land on two objects: <code class="inline">Context</code> and <code class="inline">Fiber</code>. Agents, LLMs, web are upper-layer plugins — the kernel knows none of them.',

      'why.c2.title': '<span class="pill warn">Runtime</span> No runtime lock-in',
      'why.c2.desc':  'Sync / async / thread pool / process pool are all implementations of <code class="inline">ctx.runner</code>. Switching doesn\'t require rewriting components.',

      'why.c3.title': '<span class="pill">Delivery</span> No delivery lock-in',
      'why.c3.desc':  '<code class="inline">python-cordis</code> ships the kernel only; <code class="inline">python-cordis-agent</code> provides an optional "batteries-included" plugin set, picked up by apps as needed.',

      /* ─── index: companion ─── */
      'comp.kicker':   'Companion',
      'comp.title':    'Optional batteries-included',
      'comp.banner.h': 'python-cordis-agent',
      'comp.banner.p': 'A ready-made plugin set on the application layer: agent loop, LLM seam, session log, persistence backends, web transport. All are replaceable plugins.',
      'comp.banner.a': 'View on PyPI →',

      /* ─── quickstart ─── */
      'quick.kicker':     'Up and running in 30 seconds',
      'quick.title':      'Five steps, from pip to fiber.stop().',
      'quick.tag':        'See the full path first, then dive into each detail.',

      'quick.s1.title': 'Install <span class="pill">Python ≥ 3.10</span>',
      'quick.s1.desc':  'The core package only depends on <code class="inline">pluggy</code> and <code class="inline">omegaconf</code>, no native extensions; <code class="inline">watchdog</code> is optional for file watching.',

      'quick.s2.title': 'Define the seam — the only coupling between kernel and plugins',
      'quick.s2.desc':  'Declare extension points with <code class="inline">@hookspec</code>. From then on, kernel and plugins only talk through hookspecs — the kernel knows no concrete plugin.',

      'quick.s3.title': 'Write a plugin — <code class="inline">inject</code> + <code class="inline">apply</code>',
      'quick.s3.desc':  'A plugin needs two things: an <code class="inline">inject</code> tuple declaring dependencies, and an <code class="inline">apply(ctx, ...)</code> applying side effects. <code class="inline">ctx.on</code> registers a listener, <code class="inline">ctx.effect</code> records the teardown — all revertible.',

      'quick.s4.title': 'Attach a Fiber — activates when deps are met',
      'quick.s4.desc':  'Mount the plugin on a context; <code class="inline">ctx.use</code> auto-reconciles: <code class="inline">inject</code> satisfied → activate; not satisfied → wait silently until the dep appears.',

      'quick.s5.title': 'Drive & tear down — side effects fully reverted',
      'quick.s5.desc':  'Trigger hooks, components respond on demand. When stopping a fiber, all <code class="inline">effect</code>/<code class="inline">on</code>/<code class="inline">register</code> disposers run in reverse order, no residue.',

      'quick.s6.title': 'Bonus — reactive coeffects in action',
      'quick.s6.desc':  'The snippet below shows "dependency disappears → component auto-sleeps": invoke the disposer returned by <code class="inline">register</code>, the Fiber stops Printer; re-register, it auto-rebuilds.',

      'quick.out.label':  'Expected output',
      'quick.cta.next.c': '→ Core Concepts',
      'quick.cta.next.a': '→ Architecture',

      /* ─── concepts ─── */
      'conc.h1': 'Five building blocks, one composable kernel.',
      'conc.tag': 'The two primitives from the paper <em>A Programming Paradigm for Spatiotemporal Composability</em> — <strong style="color:var(--accent)">revertible effects</strong> and <strong style="color:var(--accent)">reactive coeffects</strong> — land as five core abstractions.',

      'conc.rv.kicker': '§3.1',
      'conc.rv.h2':     'Revertible Effects',
      'conc.rv.desc':   'Every change to a context returns an idempotent disposer; teardown runs them in reverse order. Unloading a component = fully reverting all its side effects.',
      'conc.rv.th.meaning': 'Meaning',
      'conc.rv.th.returns': 'Returns',
      'conc.rv.t1.api':     '<code>ctx.register(name, value)</code>',
      'conc.rv.t1.desc':    'Bind a named service',
      'conc.rv.t1.ret':     '<code class="inline">dispose</code>',
      'conc.rv.t2.api':     '<code>ctx.set(name, value)</code>',
      'conc.rv.t2.desc':    'Same as register, plus notifies fibers that depend on it',
      'conc.rv.t2.ret':     '<code class="inline">dispose</code>',
      'conc.rv.t3.api':     '<code>ctx.effect(fn)</code>',
      'conc.rv.t3.desc':    'Record a teardown operation',
      'conc.rv.t3.ret':     '<code class="inline">dispose</code>',
      'conc.rv.t4.api':     '<code>ctx.on(hooks, name, fn)</code>',
      'conc.rv.t4.desc':    'Register a hookimpl listener',
      'conc.rv.t4.ret':     '<code class="inline">dispose</code>',
      'conc.rv.tail':       'That\'s why <code class="inline">fiber.stop()</code> can be called repeatedly and is safe on exception paths — no "double teardown" can leave dirty state.',

      'conc.co.kicker':  '§3.2',
      'conc.co.h2':      'Reactive Coeffects',
      'conc.co.desc':    'A component declares "what it needs" in <code class="inline">inject</code>; the Fiber auto-reconciles based on the actual availability of those dependencies.',
      'conc.co.th.state':'State',
      'conc.co.th.cond': 'Trigger',
      'conc.co.th.side': 'Side effect',
      'conc.co.t1.state':'ACTIVE',
      'conc.co.t1.cond': '<code>inject</code> fully satisfied',
      'conc.co.t1.side': '<code>apply()</code> ran, side effects registered',
      'conc.co.t2.state':'INACTIVE',
      'conc.co.t2.cond': '<code>inject</code> missing',
      'conc.co.t2.side': 'not activated, or already torn down',
      'conc.co.t3.state':'APPLYING',
      'conc.co.t3.cond': 'currently running <code>apply</code>',
      'conc.co.t3.side': 'lock, prevents re-entry',
      'conc.co.kw':      'Key invariants:',
      'conc.co.li1':     '<strong style="color:var(--text)">Unidirectional:</strong> on register/unregister, every fiber that declared this dep is notified.',
      'conc.co.li2':     '<strong style="color:var(--text)">Lazy:</strong> activate immediately when dep satisfied; tear down immediately when dep disappears — no manual watcher.',
      'conc.co.li3':     '<strong style="color:var(--text)">epoch:</strong> each <code>refresh()</code> round bumps <code>epoch</code>; stale notifications are dropped.',
      'conc.co.li4':     '<strong style="color:var(--text)">Inertia:</strong> re-entrant notifications fold into the next round to avoid stack overflow.',

      'conc.ctx.kicker': '§3.4',
      'conc.ctx.h2':     'Context · reflective service container',
      'conc.ctx.desc':   'Context is both the service repository and the effect boundary. It implements the paper\'s <em>context paradigm</em>: every change is recorded and revertible; every dependency change is broadcast to fibers that declared it.',
      'conc.ctx.cap1':   '# reflective lookup + parent chain',
      'conc.ctx.l1':     '# register at root',
      'conc.ctx.l2':     '# scope a child context',
      'conc.ctx.l3':     '# walk parent chain to root.fs',
      'conc.ctx.l4':     '# isolated realm from the paper',
      'conc.ctx.l5':     '# shadow parent service of same name',
      'conc.ctx.tail':   '<code class="inline">ctx.use(component)</code> creates a child context and restricts access to what the component declared in <code class="inline">inject</code> — this is the paper\'s <em>proxy-mediated enforcement</em>: undeclared access raises <code class="inline">ServiceNotFound</code>.',

      'conc.fb.kicker': '§3.3',
      'conc.fb.h2':     'Fiber · component runtime instance',
      'conc.fb.desc':   'A Fiber is the runtime wrapper of a component: it binds a component spec (<code>inject</code> + <code>apply</code>) to a context and owns its own lifecycle.',
      'conc.fb.th.api': 'Method',
      'conc.fb.th.sem': 'Semantics',
      'conc.fb.t1.api': '<code>fiber.start()</code>',
      'conc.fb.t1.desc':'Manual activation (raises if deps not satisfied)',
      'conc.fb.t2.api': '<code>fiber.stop()</code>',
      'conc.fb.t2.desc':'Manual teardown, runs disposers in reverse order',
      'conc.fb.t3.api': '<code>fiber.refresh()</code>',
      'conc.fb.t3.desc':'Reactive reconcile, auto-triggered on dependency change',
      'conc.fb.t4.api': '<code>fiber.dispose()</code>',
      'conc.fb.t4.desc':'Permanent unload, cannot be reactivated',

      'conc.hook.kicker':  'core/hook.py',
      'conc.hook.h2':      'Four hook modes',
      'conc.hook.desc':    '<code class="inline">HookRegistry</code> adds four call modes on top of pluggy, covering most plugin collaboration scenarios.',
      'conc.hook.th.mode': 'Mode',
      'conc.hook.th.beh':  'Behavior',
      'conc.hook.th.use':  'Typical use',
      'conc.hook.t1.mode': '<code>emit(name, **kw)</code>',
      'conc.hook.t1.beh':  'every listener is called, all results returned',
      'conc.hook.t1.use':  'event broadcast, metrics collection',
      'conc.hook.t2.mode': '<code>parallel(name, **kw)</code>',
      'conc.hook.t2.beh':  'thread pool runs all listeners concurrently',
      'conc.hook.t2.use':  'parallel side effects, fan-out',
      'conc.hook.t3.mode': '<code>bail(name, **kw)</code>',
      'conc.hook.t3.beh':  'first non-None return short-circuits (<code>firstresult=True</code>)',
      'conc.hook.t3.use':  'provider chains, resolvers',
      'conc.hook.t4.mode': '<code>waterfall(name, **kw)</code>',
      'conc.hook.t4.beh':  'chain delegation, each layer optionally calls <code>next</code>',
      'conc.hook.t4.use':  'middleware pipelines, command chains',
      'conc.hook.cap1':    '# → use bail mode',
      'conc.hook.cap2':    '# → use waterfall mode',
      'conc.cta.arch':     '→ Architecture',
      'conc.cta.dev':      '→ Development',

      /* ─── architecture ─── */
      'arch.h1':  'Six modules. Three layers. One kernel.',
      'arch.tag': 'The kernel only provides 6 modules and 3 abstraction layers. Concrete agent loops, LLM seams, session logs, persistence, web transport — all are ordinary replaceable plugins in the upper "application layer"; the kernel knows none of them.',

      'arch.f6.kicker':  'The 6 modules',
      'arch.f6.h2':      'F1 — F6 · six core modules',
      'arch.f6.desc':    'Each module does one thing; combined, they form the complete plugin runtime.',
      'arch.f6.th.mod':  'Module',
      'arch.f6.th.dut':  'Responsibility',
      'arch.f6.t1.num':  '<code>F1</code>',
      'arch.f6.t1.mod':  '<code>core/hook.py</code> · <code>HookRegistry</code>',
      'arch.f6.t1.dut':  'four hook call modes on top of pluggy',
      'arch.f6.t2.num':  '<code>F2</code>',
      'arch.f6.t2.mod':  '<code>core/context.py</code> · <code>Context</code>',
      'arch.f6.t2.dut':  'reflective service container, scope chain, revertible effects',
      'arch.f6.t3.num':  '<code>F3</code>',
      'arch.f6.t3.mod':  '<code>core/fiber.py</code> · <code>Fiber</code>',
      'arch.f6.t3.dut':  'component runtime instance, lifecycle + reactive reconcile',
      'arch.f6.t4.num':  '<code>F4</code>',
      'arch.f6.t4.mod':  '<code>core/config.py</code>',
      'arch.f6.t4.dut':  'OmegaConf load / override / interpolation, no code execution',
      'arch.f6.t5.num':  '<code>F5</code>',
      'arch.f6.t5.mod':  '<code>core/loader.py</code> · <code>Loader</code>',
      'arch.f6.t5.dut':  'declarative component loading, <code>reconcile</code> + <code>hot_reload</code>',
      'arch.f6.t6.num':  '<code>F6</code>',
      'arch.f6.t6.mod':  '<code>core/hmr.py</code> · <code>Reloader</code>',
      'arch.f6.t6.dut':  'transactional hot reload, rollback on failure',

      'arch.layer.kicker': 'Layered architecture',
      'arch.layer.h2':     'Three layers: Kernel ↔ Extension plugins ↔ Application',
      'arch.layer.desc':   'Arrows show dependencies: upper depends on lower; lower is unaware of upper. Green border = kernel module; orange = application-layer plugin.',
      'arch.layer.l3.tag': 'Layer 3 · Application',
      'arch.layer.l3.h4':  'Your business <code class="inline">main.py</code>',
      'arch.layer.l3.desc':'Hand a list of entries to <code class="inline">Loader.reconcile</code>, the business runs. Switching businesses doesn\'t require changing the kernel.',
      'arch.layer.l2.tag': 'Layer 2 · Companion plugins',
      'arch.layer.l2.h4':  '<code>python-cordis-agent</code> · LLM / web / persistence · …',
      'arch.layer.l2.desc':'Application-layer "ready-made plugin set": agent loop, LLM seam, session log, persistence backends, web transport — all replaceable.',
      'arch.layer.l1.tag': 'Layer 1 · Kernel',
      'arch.layer.l1.h4':  '<code>python-cordis</code> · HookRegistry / Context / Fiber / Loader / HMR',
      'arch.layer.l1.desc':'6 modules, ~1500 lines of Python. Zero business opinions — only the minimal mechanisms for "making plugins composable".',

      'arch.pe.kicker':  'Plugin discovery',
      'arch.pe.h2':      'Plugin entry-point convention',
      'arch.pe.desc':    'python-cordis itself declares no entry-point plugins; apps register their own via the standard <code class="inline">python_cordis.plugins</code> group.',
      'arch.pe.cap1':    '# your-plugin/pyproject.toml',
      'arch.pe.cap2':    '# your app',
      'arch.pe.app':     '# auto-discover all registered plugins',
      'arch.cta.dev':    '→ Development',

      /* ─── dev ─── */
      'devs.h1':  'Contribute, test, ship.',
      'devs.tag': 'python-cordis is MIT-licensed, strict-mypy, with unit tests covering all six modules. Below is the full chain from clone to release.',

      'devs.setup.kicker': '1 · Setup',
      'devs.setup.h2':     'Local development environment',
      'devs.setup.desc':   'After cloning, install in editable mode with the dev / hmr extras.',
      'devs.setup.tip':    '<code class="inline">dev</code> extra provides <code class="inline">pytest</code> / <code class="inline">pytest-cov</code> / <code class="inline">mypy</code> / <code class="inline">build</code>; <code class="inline">hmr</code> extra provides <code class="inline">watchdog</code> (optional).',

      'devs.verify.kicker': '2 · Verify',
      'devs.verify.h2':     'Test, type-check, package',
      'devs.verify.desc':   'Three things, one line; CI runs the same.',
      'devs.verify.th.cmd': 'Command',
      'devs.verify.th.eff': 'Effect',
      'devs.verify.t1.cmd': '<code>python -m mypy</code>',
      'devs.verify.t1.desc':'strict mode type check (<code class="inline">pyproject.toml [tool.mypy]</code>)',
      'devs.verify.t2.cmd': '<code>python -m pytest</code>',
      'devs.verify.t2.desc':'run the test suite (<code class="inline">tests/</code>)',
      'devs.verify.t3.cmd': '<code>python -m build</code>',
      'devs.verify.t3.desc':'produce both sdist + wheel',
      'devs.verify.cap':    '# run the full verification in one go',

      'devs.author.kicker': '3 · Author',
      'devs.author.h2':     'Write your own plugin',
      'devs.author.desc':   'A plugin is just a pair of <code class="inline">inject</code> + <code class="inline">apply</code>. Below is a complete minimum viable plugin.',
      'devs.author.tail':   'Want more examples? The <a href="concepts.html">core concepts page</a> covers revertible effects, reactive coeffects, Context, Fiber, and the four hook modes; the <a href="quickstart.html">quickstart</a> has a complete 5-minute example.',

      'devs.ship.kicker': '4 · Ship',
      'devs.ship.h2':     'Release & contribute',
      'devs.ship.desc':   'This project follows Conventional Commits; the version is maintained manually in <code class="inline">pyproject.toml</code>.',
      'devs.ship.c1.h':   'TestPyPI rehearsal',
      'devs.ship.c1.desc':'<code class="inline">python -m build</code> + <code class="inline">twine upload --repository testpypi dist/*</code> dry-run on TestPyPI first, to avoid polluting the real index.',
      'devs.ship.c2.h':   'Real release',
      'devs.ship.c2.desc':'Bump <code class="inline">version</code> in <code class="inline">pyproject.toml</code>, sync <code class="inline">__version__</code>, tag, and push <code class="inline">twine upload dist/*</code>.',
      'devs.ship.c3.h':   'Open a PR',
      'devs.ship.c3.desc':'fork → feature branch → commit → PR. CI runs mypy + pytest; keep strict mode clean.',
      'devs.ship.tail':   'See the full contribution guide on the <a href="https://github.com/peroxider/python-cordis">GitHub repo</a>. License: <code class="inline">MIT</code> · Python ≥ 3.10.',
      'devs.cta.home':    '← Home',
      'devs.cta.gh':      'GitHub →',

      /* ─── footer ─── */
      'foot.tag': 'Written in Python, for the Python ecosystem.',
      'foot.lic': 'MIT License',

      /* ─── code-block comments ─── */
      'code.hero.c1':  "# inject=('config',) satisfied",
      'code.hero.c2':  '# Printer.apply registered the hookimpl',
      'code.hero.c3':  'teardown runs in reverse, all side effects fully reverted',
      'code.qs3.c1':   '# reactive coeffect: activated when deps are satisfied',
      'code.qs4.c1':   '# True: dependency satisfied',
      'code.qs5.c1':   '# printer torn down   ← ctx.effect lambda auto-invoked',
      'code.qs6.c1':   '# revoke service → refresh fires, fiber auto-stops',
      'code.qs6.c2':   '# True — auto-recovered',
      'code.crv.c1':   '# after one call armed = False, subsequent calls are no-op',
      'code.crv.c2':   '# tear down',
      'code.crv.c3':   '# safe — idempotent',
      'code.arch.c1':  '# the simplest possible "boot the app"',
      'code.arch.c2':  '# incremental reconcile',
      'code.arch.c3':  '# edit file → auto-reload, rollback on failure',
      'code.dev.c1':   '# no deps required → activate immediately',
      'code.dev.c2':   '# reversible teardown',
    },
  };

  function detect() {
    try {
      const stored = localStorage.getItem(STORE_KEY);
      if (stored && I18N[stored]) return stored;
    } catch (_) { /* ignore */ }
    const lang = (navigator.language || 'en').toLowerCase();
    return lang.startsWith('zh') ? 'zh' : 'en';
  }

  function apply(lang) {
    if (!I18N[lang]) lang = 'en';
    const dict = I18N[lang];
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
    document.querySelectorAll('[data-i18n]').forEach((el) => {
      const key = el.getAttribute('data-i18n');
      if (dict[key] != null) el.textContent = dict[key];
    });
    document.querySelectorAll('[data-i18n-html]').forEach((el) => {
      const key = el.getAttribute('data-i18n-html');
      if (dict[key] != null) el.innerHTML = dict[key];
    });
    document.querySelectorAll('[data-lang-toggle]').forEach((b) => {
      b.textContent = lang === 'zh' ? 'EN' : '中';
    });
    try { localStorage.setItem(STORE_KEY, lang); } catch (_) { /* ignore */ }
  }

  function toggle() {
    const cur = document.documentElement.lang === 'zh-CN' ? 'zh' : 'en';
    apply(cur === 'zh' ? 'en' : 'zh');
  }

  function init() {
    const lang = detect();
    apply(lang);
    document.querySelectorAll('[data-lang-toggle]').forEach((b) => {
      b.addEventListener('click', toggle);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();