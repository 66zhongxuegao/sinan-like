"""文化桥 · 十大客源国：找中国和对方的共通点，用于入境游定制师的跨文化沟通。

定位：不是「外国风俗百科」，而是**共同点**——先找到能共鸣的地方，再谈差异，
这样学员面对入境客人时有可用的切入角度（吃的、家的、面子的、时间的、送礼的）。

每条包含：
  point   共通点（一句话）
  china   中国这边的表现
  theirs  对方那边的表现
  use     对定制师怎么用（落到行程、餐食、沟通话术）
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Bridge:
    code: str
    name: str
    country: str
    language: str
    summary: str
    points: list[dict] = field(default_factory=list)
    pitfalls: list[str] = field(default_factory=list)


BRIDGES: list[Bridge] = [
    Bridge(
        code="US", name="中美文化桥", country="美国", language="English",
        summary="重视家庭时间、教育投入与个人空间；把「被尊重」看得比「被照顾」更重。",
        points=[
            {"point": "家庭聚餐是重要仪式", "china": "年夜饭、团圆饭讲究人多热闹",
             "theirs": "Thanksgiving / 家庭晚餐同样郑重，习惯围桌聊天", "use": "安排一次有仪式感的合家宴，比堆景点更容易赢得好评"},
            {"point": "重视教育投入", "china": "家长愿为孩子的见识买单",
             "theirs": "带孩子旅行看重「学到了什么」", "use": "行程里加可讲故事的环节（博物馆讲解、非遗手作），家长会觉得值"},
            {"point": "讲个人空间与边界", "china": "热情好客常表现为时刻陪伴",
             "theirs": "需要独处时间与明确安排", "use": "给出留白时段和清晰的每日时间表，别安排满"},
            {"point": "对服务失误看「态度」", "china": "先认错再补救是常识",
             "theirs": "看重对方是否真诚处理、有无补偿动作", "use": "出问题时先担责再给方案，别先解释原因"},
        ],
        pitfalls=["别用「我们中国人都……」的概括开场", "避免把「便宜」当卖点，对方更在意省心与确定性"],
    ),
    Bridge(
        code="KR", name="中韩文化桥", country="韩国", language="한국어",
        summary="同属东亚礼仪圈：重长辈、重面食与酒桌、重拍照与「打卡」体验。",
        points=[
            {"point": "长幼有序、敬语文化", "china": "尊老、讲究称呼与座次",
             "theirs": "敬语体系更细，年龄决定称呼与语气", "use": "安排座位与介绍顺序时把年长者放前面，容易建立信任"},
            {"point": "吃饭要有「主角菜」", "china": "一桌要有一道压桌菜",
             "theirs": "一顿要有明确的主菜与汤", "use": "餐食按「一主菜一汤」配，比多而杂更受欢迎"},
            {"point": "酒桌是社交场", "china": "敬酒、碰杯讲关系",
             "theirs": "喝酒讲辈分与倒酒顺序", "use": "安排有氛围的小馆，别安排成赶时间的快餐"},
            {"point": "爱拍照、重审美", "china": "打卡照、精修图",
             "theirs": "对画面与氛围更挑剔", "use": "行程里给两三个「出片」位点，客人的自发传播就是口碑"},
        ],
        pitfalls=["别把韩国客人当「会说中文的国内客人」，敬语与称呼要区别对待"],
    ),
    Bridge(
        code="JP", name="中日文化桥", country="日本", language="日本語",
        summary="同属汉字文化圈：重季节感、重秩序与守时、重细节上的「周到」。",
        points=[
            {"point": "季节感", "china": "讲究应季食材与节气",
             "theirs": "对花期、旬物、季节限定的执念很强", "use": "行程按花期与当季食材设计，客人会觉得被认真对待"},
            {"point": "守时与秩序", "china": "重要场合提前到",
             "theirs": "时刻表精确到分钟", "use": "所有时间点写清楚并留缓冲，延误要提前打招呼"},
            {"point": "伴手礼文化", "china": "带点土特产",
             "theirs": "送礼讲究包装与场合", "use": "准备小份、有包装、可解释来由的伴手礼"},
            {"point": "委婉表达", "china": "婉拒也留余地",
             "theirs": "「有点难」往往就是不行", "use": "听到犹豫就主动给替代方案，别硬推"},
        ],
        pitfalls=["别用大嗓门与催促式的沟通", "别把「茶」当成万能话题——对方可能更在意器与礼"],
    ),
    Bridge(
        code="SG", name="中新文化桥", country="新加坡", language="English / 中文 / Malay",
        summary="多语多族社会，华族占多数但英语优先，讲效率、讲规则、讲食品安全。",
        points=[
            {"point": "华族家庭的祖籍情结", "china": "认祖归宗、宗祠与族谱",
             "theirs": "不少家庭仍知道祖籍地（福建、潮州、海南）", "use": "问出祖籍并安排寻根点，是最有效的破冰"},
            {"point": "小贩中心与街头美食", "china": "夜市、小吃街",
             "theirs": "hawker centre 是国民日常", "use": "安排一次本地食阁体验，比高档餐厅更让客人有共鸣"},
            {"point": "重规则与效率", "china": "讲人情、可商量",
             "theirs": "习惯按规则办、流程清楚", "use": "合同、保险、发票讲清流程，减少来回解释"},
            {"point": "多种族礼仪", "china": "一桌人忌口要问",
             "theirs": "清真、素食、不饮酒都可能出现", "use": "默认问一遍饮食禁忌，按清真/素食给备选"},
        ],
        pitfalls=["别默认「会说中文」就按国内客人沟通——商务语境英语更稳妥"],
    ),
    Bridge(
        code="MY", name="中马文化桥", country="马来西亚", language="Bahasa / English / 中文",
        summary="多元族裔（马来、华族、印度裔），华族保留浓厚的闽粤传统，清真饮食是硬约束。",
        points=[
            {"point": "华族饮食传统完整", "china": "闽粤菜系、节庆糕粿",
             "theirs": "肉骨茶、福建面、粿条都是日常", "use": "带客人吃地道的闽粤与客家菜，情感连接最强"},
            {"point": "过节方式相似", "china": "春节走亲访友、红包",
             "theirs": "华人春节同样拜年、捞鱼生", "use": "遇上节庆可安排年味体验（庙会、灯会）"},
            {"point": "清真饮食是硬约束", "china": "清真餐厅在小范围",
             "theirs": "马来族客人必须清真认证", "use": "默认确认族裔与禁忌，清真餐厅要认准认证标识"},
            {"point": "家族出行规模大", "china": "三代同游常见",
             "theirs": "同样习惯带老人小孩", "use": "用车与房型按三代考虑，节奏放慢"},
        ],
        pitfalls=["别把「会说中文」等同华族——可能是马来族或印度裔，饮食与称呼都不同"],
    ),
    Bridge(
        code="TH", name="中泰文化桥", country="泰国", language="ไทย",
        summary="佛教文化浓厚，重礼貌与「面子」，喜欢轻松愉快、不喜正面冲突。",
        points=[
            {"point": "佛教底色", "china": "寺庙、烧香、拜佛",
             "theirs": "佛教是生活一部分，对僧侣与寺庙极尊重", "use": "安排寺院参访时说清礼仪（着装、脱鞋、不背对佛像）"},
            {"point": "重「不扫兴」", "china": "来都来了、要给面子",
             "theirs": "更倾向避免正面冲突，不满也常笑着说", "use": "主动确认满意度，别把「对方没抱怨」当成满意"},
            {"point": "对长辈与皇室的尊重", "china": "尊老",
             "theirs": "对王室极尊重，对长者用敬语", "use": "涉及相关话题保持克制，别开玩笑"},
            {"point": "饮食酸辣甜并存", "china": "重口味能接受",
             "theirs": "口味偏酸辣甜、量小分次", "use": "餐食安排多次小份，避免长途车程后吃重油大餐"},
        ],
        pitfalls=["别用脚指方向、别摸人头——在泰国是失礼行为"],
    ),
    Bridge(
        code="VN", name="中越文化桥", country="越南", language="Tiếng Việt",
        summary="同属汉字与节庆文化圈，家族观念强，重实用与价格透明度。",
        points=[
            {"point": "同样的农历节庆", "china": "春节、清明、中秋",
             "theirs": "Tết 与春节同源，同样讲究返乡团圆", "use": "节庆期间要提前锁资源，并理解客人可能带大家庭"},
            {"point": "家族共同决策", "china": "有事商量着来",
             "theirs": "长辈意见权重高", "use": "重要变更主动请对方与家人确认，别只对接一个人"},
            {"point": "重视实际价值", "china": "讲性价比",
             "theirs": "对价格与内容是否对等很敏感", "use": "报价分项写清，避免模糊打包价"},
            {"point": "与中国口味相近", "china": "米饭、汤粉、酱油",
             "theirs": "河粉、米饭、清淡汤品为主", "use": "餐食不必大改，但避免过油过辣"},
        ],
        pitfalls=["别把越南客人默认成「会说中文」，中文普及度有限"],
    ),
    Bridge(
        code="ID", name="中印尼文化桥", country="印度尼西亚", language="Bahasa Indonesia",
        summary="全球穆斯林人口最多的国家，家族观念强，节奏偏松弛，重礼节与温和沟通。",
        points=[
            {"point": "重视家族与团聚", "china": "逢年过节要团圆",
             "theirs": "开斋节返乡（mudik）是年度大事", "use": "尊重斋月作息：白天不安排重体力行程，日落后再安排正餐"},
            {"point": "礼节与问候", "china": "寒暄再谈事",
             "theirs": "更讲究慢慢建立关系", "use": "前两轮沟通别急着报价，先把需求聊透"},
            {"point": "时间观念偏松弛", "china": "重要行程会按时",
             "theirs": "«jam karet» 弹性时间", "use": "关键节点（航班、高铁）留足缓冲并反复提醒"},
            {"point": "饮食禁忌明确", "china": "忌口要问",
             "theirs": "清真为主，不饮酒", "use": "默认按清真配餐，宴请不要劝酒"},
        ],
        pitfalls=["别安排含猪肉或酒水的默认餐食", "斋月期间别把行程排到晚上没有用餐时间"],
    ),
    Bridge(
        code="GB", name="中英文化桥", country="英国", language="English",
        summary="重礼貌与排队秩序、爱博物馆与花园、用幽默与自嘲沟通，讨厌被过度推销。",
        points=[
            {"point": "礼貌与排队", "china": "讲礼数、重场合",
             "theirs": "排队与致谢是社交底线", "use": "所有安排写清楚顺序与时间，别出现插队或加塞感"},
            {"point": "博物馆与历史", "china": "喜欢逛古迹与博物馆",
             "theirs": "博物馆是国民习惯", "use": "行程里给博物馆留足时间（2-3 小时），别只打卡"},
            {"point": "花园与园林情结", "china": "园林、茶室、盆景",
             "theirs": "园艺是全民爱好", "use": "安排一次园林或茶空间体验，比购物更受欢迎"},
            {"point": "自嘲式幽默", "china": "客气话与自谦",
             "theirs": "习惯用幽默化解尴尬", "use": "听不懂笑话时微笑顺势接话，别追问含义"},
        ],
        pitfalls=["别把「礼貌」当「同意」——对方说 quite interesting 往往是不感兴趣"],
    ),
    Bridge(
        code="AU", name="中澳文化桥", country="澳大利亚", language="English",
        summary="休闲务实、重视户外与家庭时间、反感被安排得过满，直接沟通但不失礼貌。",
        points=[
            {"point": "家庭与休闲优先", "china": "假期集中出游",
             "theirs": "假期碎片化，重视放松", "use": "节奏放慢，每天一到两个重点，其余时间自由"},
            {"point": "户外与自然", "china": "山水游、徒步",
             "theirs": "户外是生活方式", "use": "安排自然景观与轻徒步，注意安全说明"},
            {"point": "直接但不失礼", "china": "有话直说是爽快",
             "theirs": "表达直接，但介意被冒犯", "use": "报价与变更直说，别绕弯子；同时保持礼貌措辞"},
            {"point": "对动植物与环保敏感", "china": "关心食品安全",
             "theirs": "关心生态保护与动物福利", "use": "别安排动物表演类项目，优先考虑生态友好的体验"},
        ],
        pitfalls=["别安排密集购物点", "别把「远途赶景点」当成卖点"],
    ),
]


def all_bridges() -> list[Bridge]:
    return BRIDGES


def get(code: str) -> Bridge | None:
    for b in BRIDGES:
        if b.code.lower() == (code or "").lower():
            return b
    return None


def as_payload(b: Bridge) -> dict:
    return {
        "code": b.code, "name": b.name, "country": b.country, "language": b.language,
        "summary": b.summary, "points": b.points, "pitfalls": b.pitfalls,
        "point_count": len(b.points),
    }