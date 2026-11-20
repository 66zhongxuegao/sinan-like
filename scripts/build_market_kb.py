"""生成 data/markets/*.json（国别知识库）。一次性脚本：改内容请改这里再重新生成。

内容原则：
- 每条都有标题头 + 一两句正文，不求多，求能直接在讲义里引用；
- 政策类一律标 verify=true，正文只写稳定的框架，具体名单/天数/有效期写明「以官方最新公告为准」；
- 外语客服用语只放最常用的 6 句，供低水平学员照读；更高水平的表达由讲义按水平另行补充。
"""
import json
from pathlib import Path

OUT = Path(r"D:\司南礼客项目\data\markets")
OUT.mkdir(parents=True, exist_ok=True)

SRC = {
    "nia": {"id": "nia", "title": "国家移民管理局（入出境政策）", "url": "https://www.nia.gov.cn/"},
    "mfa": {"id": "mfa", "title": "外交部领事服务网（签证与领事信息）", "url": "https://cs.mfa.gov.cn/"},
    "mct": {"id": "mct", "title": "文化和旅游部（入境旅游）", "url": "https://www.mct.gov.cn/"},
    "fmprc": {"id": "fmprc", "title": "外交部 · 国家和地区（国别概况）", "url": "https://www.fmprc.gov.cn/web/gjhdq_676201/"},
}

SCENES = ["欢迎问候", "表示感谢", "确认预算口径", "询问饮食禁忌", "致歉", "请对方稍等"]
ZH = ["欢迎来到中国，我是您的定制师。", "谢谢您的耐心。", "请问这个预算是每人的，还是整个团的总价？",
      "请问有饮食禁忌或过敏吗？", "抱歉给您添麻烦了。", "请稍等，我马上确认。"]


def phrases(texts, reads=None):
    reads = reads or [""] * 6
    return [{"scene": SCENES[i], "zh": ZH[i], "text": texts[i], "read": reads[i]} for i in range(6)]


EN = phrases([
    "Welcome to China. I'm your tailor-made trip planner.", "Thank you for your patience.",
    "Is this budget per person, or for the whole group?", "Do you have any dietary restrictions or allergies?",
    "I'm sorry for the inconvenience.", "One moment, please. Let me confirm that for you."])
JA = phrases([
    "ようこそ中国へ。担当のプランナーです。", "ありがとうございます。", "ご予算は一人あたりですか、全体ですか？",
    "食べ物のアレルギーや苦手なものはありますか？", "ご迷惑をおかけして申し訳ございません。", "少々お待ちください。確認いたします。"],
    ["Yōkoso Chūgoku e. Tantō no puranā desu.", "Arigatō gozaimasu.", "Go-yosan wa hitori atari desu ka, zentai desu ka?",
     "Tabemono no arerugī ya nigate na mono wa arimasu ka?", "Go-meiwaku o okake shite mōshiwake gozaimasen.", "Shōshō omachi kudasai. Kakunin itashimasu."])
KO = phrases([
    "중국에 오신 것을 환영합니다. 담당 플래너입니다.", "감사합니다.", "예산은 1인당인가요, 전체인가요?",
    "못 드시는 음식이나 알레르기가 있으신가요?", "불편을 드려 죄송합니다.", "잠시만 기다려 주세요. 확인해 드리겠습니다."],
    ["Jungguge osin geoseul hwanyeonghamnida. Damdang peullaeneoimnida.", "Gamsahamnida.", "Yesaneun irindang-ingayo, jeoncheingayo?",
     "Mot deusineun eumsigina allereugiga isseusingayo?", "Bulpyeoneul deuryeo joesonghamnida.", "Jamsiman gidaryeo juseyo. Hwaginhae deurigetseumnida."])
TH = phrases([
    "ยินดีต้อนรับสู่ประเทศจีนค่ะ/ครับ", "ขอบคุณค่ะ/ครับ", "งบประมาณนี้ต่อคน หรือรวมทั้งกลุ่มคะ/ครับ",
    "มีอาหารที่แพ้หรือทานไม่ได้ไหมคะ/ครับ", "ขออภัยในความไม่สะดวกค่ะ/ครับ", "รอสักครู่นะคะ/ครับ ขอตรวจสอบก่อน"],
    ["Yindi ton rap su prathet Chin kha/khrap（女性用 kha，男性用 khrap）", "Khop khun kha/khrap", "Ngop pramaan ni to khon rue ruam thang klum kha/khrap",
     "Mi ahan thi phae rue than mai dai mai kha/khrap", "Kho aphai nai khwam mai saduak kha/khrap", "Ro sakkhru na kha/khrap kho truat sop kon"])
VI = phrases([
    "Chào mừng bạn đến Trung Quốc. Tôi là người lên kế hoạch hành trình cho bạn.", "Cảm ơn bạn đã kiên nhẫn.",
    "Ngân sách này là cho mỗi người hay cho cả nhóm ạ?", "Bạn có kiêng món ăn nào hoặc bị dị ứng không ạ?",
    "Xin lỗi vì sự bất tiện này ạ.", "Xin chờ một chút, tôi sẽ xác nhận ngay ạ."])
ID_ = phrases([
    "Selamat datang di Tiongkok. Saya perencana perjalanan Anda.", "Terima kasih atas kesabaran Anda.",
    "Apakah anggaran ini per orang atau untuk seluruh rombongan?", "Apakah Anda punya pantangan makanan atau alergi?",
    "Mohon maaf atas ketidaknyamanannya.", "Mohon tunggu sebentar, saya akan memastikannya."])
RU = phrases([
    "Добро пожаловать в Китай. Я ваш планировщик поездки.", "Спасибо за ваше терпение.",
    "Этот бюджет на одного человека или на всю группу?", "Есть ли у вас пищевые ограничения или аллергия?",
    "Приносим извинения за неудобства.", "Одну минуту, я сейчас уточню."],
    ["Dobro pozhalovat' v Kitay. Ya vash planirovshchik poyezdki.", "Spasibo za vashe terpeniye.", "Etot byudzhet na odnogo cheloveka ili na vsyu gruppu?",
     "Yest' li u vas pishchevyye ogranicheniya ili allergiya?", "Prinosim izvineniya za neudobstva.", "Odnu minutu, ya seychas utochnyu."])
DE = phrases([
    "Willkommen in China. Ich bin Ihr Reiseplaner.", "Vielen Dank für Ihre Geduld.", "Gilt dieses Budget pro Person oder für die ganze Gruppe?",
    "Haben Sie Ernährungseinschränkungen oder Allergien?", "Entschuldigen Sie bitte die Unannehmlichkeiten.", "Einen Moment bitte, ich kläre das sofort für Sie."])
FR = phrases([
    "Bienvenue en Chine. Je suis votre planificateur de voyage.", "Merci beaucoup pour votre patience.",
    "Ce budget est-il par personne ou pour tout le groupe ?", "Avez-vous des restrictions alimentaires ou des allergies ?",
    "Veuillez nous excuser pour la gêne occasionnée.", "Un instant, je vérifie cela tout de suite."])
IT = phrases([
    "Benvenuti in Cina. Sono il vostro pianificatore di viaggio.", "Grazie mille per la pazienza.",
    "Questo budget è a persona o per tutto il gruppo?", "Avete restrizioni alimentari o allergie?",
    "Ci scusiamo per il disagio.", "Un momento, verifico subito."])
AR = phrases([
    "مرحباً بكم في الصين. أنا مخطط رحلتكم.", "شكراً جزيلاً على صبركم.", "هل هذه الميزانية للشخص الواحد أم للمجموعة كلها؟",
    "هل لديكم قيود غذائية أو حساسية؟", "نعتذر عن الإزعاج.", "لحظة من فضلكم، سأتأكد الآن."],
    ["Marhaban bikum fi as-Sin. Ana mukhattit rihlatikum.", "Shukran jazilan 'ala sabrikum.", "Hal hadhihi al-mizaniyya lil-shakhs al-wahid am lil-majmu'a kullihā?",
     "Hal ladaykum quyud ghidha'iyya aw hasasiyya?", "Na'tadhir 'an al-iz'aj.", "Lahza min fadlikum, sa-ata'akkad al-an."])

SHARED_POLICY = [
    {"title": "入境中国：免签与过境免签（需核验）",
     "body": "我国近年对多个国家实施单方面免签或互免签证，并实行 144/240 小时过境免签。各国适用名单、可停留天数和有效期会不时调整，"
             "做方案前必须到国家移民管理局官网核对该国公民当前适用的政策，不要凭记忆向客人承诺。过境免签要求联程机票"
             "（出发国→中国→第三国或地区），往返同一国家不适用。",
     "verify": True, "sources": ["nia", "mfa"]},
    {"title": "通讯与支付：行前提醒（需核验）",
     "body": "部分海外常用的搜索、地图、社交应用在境内可能无法正常使用，建议客人行前准备可用的翻译与地图工具、eSIM 或漫游方案；"
             "境外银行卡可绑定支付宝、微信支付后使用，但部分场所仍以现金或银联为主，具体以平台最新规则为准。",
     "verify": True, "sources": []},
]

# code: (中文名, 区域, 服务语言, 题面语言简称, 短语库, 旅游局链接(标题,url), 文化[], 习俗[], 政策补充[] )
M = {
 "US": ("美国", "北美", "英语", "英语", EN, ("美国旅游局 Brand USA", "https://www.visittheusa.com/"),
  [("重视个人空间与选择权", "习惯被询问偏好、被给出几个选项，而不是被安排；行程里要留出自由活动的时间。"),
   ("直接表达、重视效率", "沟通偏直接，喜欢先听结论再听理由；报价与行程要清晰、条目化，避免绕弯。")],
  [("小费习惯", "美国客人习惯给小费，而中国大陆多数场合不需要小费，行前要提醒，以免产生尴尬或误会。"),
   ("饮食过敏意识强", "过敏与特殊饮食（素食、无麸质、无乳糖）在美国很常见，下单餐厅前务必确认并书面记录。")], []),
 "KR": ("韩国", "东亚", "韩语", "韩语", KO, ("韩国观光公社", "https://english.visitkorea.or.kr/"),
  [("长幼有序与敬语", "称呼与座次以年龄、职位为序，介绍和敬酒先长辈；对年长客人使用敬语，更容易建立信任。"),
   ("重视体验与拍照出片", "对环境氛围和拍照点要求较高，行程中安排两三个适合出片的点位更受欢迎。")],
  [("餐桌礼仪", "长辈先动筷，晚辈再动；韩餐偏辣，也有不吃辣的客人，点餐前要确认。"),
   ("酒文化", "聚餐常有敬酒环节，倒酒与接酒用双手；若客人不饮酒，要提前问清，不要劝酒。")], []),
 "JP": ("日本", "东亚", "日语", "日语", JA, ("日本政府观光局 JNTO", "https://www.japan.travel/"),
  [("守时与秩序", "极度重视守时和排队；行程时间表要准确，延误要提前说明原因和新时间。"),
   ("含蓄表达，不爱添麻烦", "很少直接拒绝，「再考虑一下」往往意味着不满意；要主动确认，而不是等客人开口投诉。")],
  [("名片与称呼", "接递名片用双手，称呼带「様/さん」；初次沟通务必自报公司与姓名。"),
   ("环境与礼仪", "公共场所安静，垃圾通常自行带走；进入室内鞋子的规矩要事先说明。")], []),
 "SG": ("新加坡", "东南亚", "英语", "英语", EN, ("新加坡旅游局", "https://www.visitsingapore.com/"),
  [("多语多族群", "英语为通用语，华语、马来语、泰米尔语并存；沟通前先确认客人更习惯的语言。"),
   ("效率与诚信", "对价格透明、守约、效率要求高，不喜欢含糊的报价。")],
  [("饮食多元", "穆斯林清真、素食、不吃牛肉等并存，团餐必须逐项确认。"),
   ("对服务细节挑剔", "预订的房型、车型、时间要书面确认，临时变更要提前告知并给出补救方案。")], []),
 "MY": ("马来西亚", "东南亚", "英语", "英语", EN, ("马来西亚旅游局", "https://www.malaysia.travel/"),
  [("多元族群", "马来、华人、印度裔并存，华人客人通常可以直接用中文沟通；先问清客人习惯的语言，再切换。"),
   ("宗教与节日意识", "穆斯林客人有祈祷与斋月安排，行程要避开主要礼拜时间并预留祈祷空间。")],
  [("清真饮食", "穆斯林客人要求清真（Halal）餐饮，不食猪肉与酒类；订餐要确认厨房与食材是否合规。"),
   ("日常礼仪", "递物、接物用右手或双手；避免触碰他人头部，坐姿不要把脚底对着人。")], []),
 "TH": ("泰国", "东南亚", "泰语", "泰语", TH, ("泰国旅游局", "https://www.tourismthailand.org/"),
  [("佛教文化与尊重", "头部被视为神圣，不要触碰客人头部；对王室和佛像保持尊重，行程中的讲解避免随意评论。"),
   ("轻松友善、重视面子", "不喜欢冲突与当面批评，沟通语气要柔和，出问题时用商量的口吻提出方案。")],
  [("寺庙着装", "参观寺庙要遮住肩膀和膝盖；脚不要指向人或佛像，进入殿堂需脱鞋。"),
   ("合十礼", "常以合十致意，对方先行礼时回礼即可，不必强行握手。")], []),
 "VN": ("越南", "东南亚", "越南语", "越南语", VI, ("越南国家旅游局", "https://vietnam.travel/"),
  [("重视礼貌与长幼", "称呼要带上辈分或职衔，对年长客人更要恭敬；多用「ạ」等敬语语气词可以拉近关系。"),
   ("重视人情与面子", "不喜欢被当面否定，提出调整时先肯定客人的想法，再给出替代方案。")],
  [("饮食偏好", "喜欢鲜香、清淡、多香草的口味；咖啡与街头小吃是体验亮点，可安排到行程里。"),
   ("敏感话题回避", "行程与讲解中避免触及政治、边界与历史争议话题。")], []),
 "ID": ("印度尼西亚", "东南亚", "印尼语", "印尼语", ID_, ("印度尼西亚旅游部", "https://www.indonesia.travel/"),
  [("穆斯林为主的社会", "每日五次礼拜，斋月作息会变化；行程避开礼拜时间并为客人预留祈祷空间。"),
   ("重视和谐与礼貌", "说话温和，不爱直接说「不」；要多确认，不要把沉默当作同意。")],
  [("清真饮食", "不食猪肉与酒类，要求清真（Halal）餐饮；巴厘岛客人则可能是印度教徒，不吃牛肉。"),
   ("手与头的礼仪", "用右手递物与进食，左手被视为不洁；不要触碰他人头部。")], []),
 "GB": ("英国", "欧洲", "英语", "英语", EN, ("英国旅游局 VisitBritain", "https://www.visitbritain.com/"),
  [("排队与礼貌用语", "非常看重排队和 please / thank you / sorry；服务沟通要礼貌、克制，不要过度热情推销。"),
   ("含蓄与幽默", "批评常以委婉方式表达，「not bad」可能只是一般；要主动追问真实感受。")],
  [("茶与饮食", "喝茶是日常习惯，酒店与车上备热水和茶会加分；注意素食与过敏需求。"),
   ("守时与隐私", "守时是基本礼貌，对个人隐私敏感，不要随意询问年龄、收入等。")], []),
 "AU": ("澳大利亚", "大洋洲", "英语", "英语", EN, ("澳大利亚旅游局", "https://www.australia.com/"),
  [("随和直接、不拘小节", "沟通轻松直率，不喜欢过于正式的客套；称呼用名字即可，但承诺要兑现。"),
   ("户外与环保意识", "偏爱户外与自然体验，重视环保，行程里要有可持续、少一次性用品的选择。")],
  [("饮食多样", "素食、无麸质者较多；饮用水、防晒与时差休整要在行前提示。"),
   ("小费不强制", "小费并非强制，不要给客人造成「必须给」的压力。")], []),
 "RU": ("俄罗斯", "欧洲/北亚", "俄语", "俄语", RU, ("俄罗斯旅游局", "https://russia.travel/"),
  [("直接坦率、重诚信", "不喜欢过度客套，更看重诚实、清晰的报价和明确的承诺；不确定的事情直说，比含糊更受信任。"),
   ("重视服务与细节", "对酒店房型、餐食分量与交通舒适度要求具体，建议书面确认。")],
  [("饮食与茶", "偏好分量足的热食与热茶，不太习惯过多凉菜；要提前问清是否吃辣。"),
   ("礼仪细节", "进入室内常会脱外套，送花的数量习惯用单数；对客人的问候要真诚而不过分热络。")], []),
 "DE": ("德国", "欧洲", "德语", "德语", DE, ("德国国家旅游局", "https://www.germany.travel/"),
  [("严谨与守时", "重视计划、规则与守时；行程要提前给出详细书面版本，变更必须解释原因。"),
   ("环保与步行偏好", "喜欢步行、骑行与自然体验，重视环保；对一次性用品和浪费较敏感。")],
  [("饮食", "素食、清淡饮食者比例不低；餐厅要问清过敏源，价格与结账方式要清楚。"),
   ("直接沟通", "沟通偏直接、重事实，不喜欢夸张的话术，提供数据与依据更有说服力。")], []),
 "FR": ("法国", "欧洲", "法语", "法语", FR, ("法国旅游发展署", "https://www.france.fr/"),
  [("重视礼貌与问候", "见面先打招呼（Bonjour）再进入正题，这在法国是基本礼貌；直接开口谈事会显得无礼。"),
   ("饮食与文化体验", "重视美食、艺术与慢节奏体验，不适合把行程排得太满。")],
  [("用餐时间长", "用餐被视为社交，午餐和晚餐时间较长，行程要给用餐留足时间。"),
   ("对服务品质挑剔", "对餐厅与酒店的品质敏感，宁可少而精，也不要为了数量牺牲体验。")], []),
 "IT": ("意大利", "欧洲", "意大利语", "意大利语", IT, ("意大利国家旅游局", "https://www.italia.it/"),
  [("重视家庭与美食", "家庭出行较多，用餐是核心体验；餐厅的品质与氛围比数量更重要。"),
   ("热情、重视人情", "沟通热情，喜欢被当作朋友而非客户；过度冷冰冰的流程化沟通会降低好感。")],
  [("饮食习惯", "对本国饮食很讲究，团餐中可以安排一两顿地道中餐体验，同时备有清淡、简单的备选。"),
   ("节奏与时间", "对时间的弹性较大，但对服务缺失敏感；关键节点要提前反复确认。")], []),
 "CA": ("加拿大", "北美", "英语", "英语", EN, ("加拿大旅游局", "https://www.destinationcanada.com/"),
  [("多元包容、讲礼貌", "社会多元，英语与法语并存；沟通礼貌、尊重差异，避免对任何群体作概括性评价。"),
   ("重视自然与家庭体验", "偏爱自然风光与深度体验，也重视带孩子出游时的安全与舒适。")],
  [("小费习惯", "习惯给小费，在中国大陆多数场合不需要，行前要说明，避免尴尬。"),
   ("饮食需求多样", "素食、过敏和宗教饮食都较常见，下单前要逐项确认。")], []),
 "IN": ("印度", "南亚", "英语", "英语", EN, ("印度旅游部", "https://www.incredibleindia.gov.in/"),
  [("宗教与饮食禁忌多元", "印度教徒通常不吃牛肉，许多客人是素食者，穆斯林不吃猪肉；订餐前必须逐人确认。"),
   ("重视家庭与群体", "常以家庭或大家族出行，决策人未必是出钱的人，沟通时要弄清谁拍板。")],
  [("左手与头的礼仪", "不用左手递物或进食；不要触碰他人头部。点头与摇头的含义和中国不同，需要口头再确认。"),
   ("问候", "常用双手合十的 Namaste 问候，可以主动致意，会很加分。")], []),
 "SA": ("沙特阿拉伯", "中东", "阿拉伯语", "阿拉伯语", AR, ("沙特旅游局", "https://www.visitsaudi.com/"),
  [("伊斯兰教生活规范", "每日五次礼拜，斋月期间作息变化；行程要避开礼拜时间并为客人预留祈祷空间。"),
   ("重视家庭、长辈与待客", "家庭出行常见，要尊重长辈与家庭决策人；对待客礼仪非常看重，招待要体面。")],
  [("清真饮食与禁忌", "必须是清真（Halal）餐饮，不食猪肉与酒类；订餐要确认食材与烹饪是否合规。"),
   ("男女交往礼仪", "与异性握手要等对方主动；陌生人之间保持距离，拍照前先征得同意，尤其不要拍摄女性。")], []),
 "NZ": ("新西兰", "大洋洲", "英语", "英语", EN, ("新西兰旅游局", "https://www.newzealand.com/"),
  [("热爱自然、重视环保", "偏爱户外、徒步与自然体验，重视环保与可持续；行程要有户外活动并尊重自然。"),
   ("随和友好、尊重毛利文化", "沟通随和不拘小节；对毛利文化很有认同感，相关体验是亮点，要以尊重的态度介绍。")],
  [("饮食与小费", "素食、无麸质者较多；小费不强制，不必给客人压力。"),
   ("安全与保险意识", "户外活动前客人会关心安全与保险，要主动提供清晰的安全说明与保险信息。")], []),
}

for code, (country, region, lang, lang_short, ph, tourism, culture, customs, extra_policy) in M.items():
    sources = [SRC["nia"], SRC["mfa"], SRC["mct"], SRC["fmprc"],
               {"id": "tourism", "title": f"{country}官方旅游推广机构：{tourism[0]}", "url": tourism[1]}]
    policy = [dict(p) for p in SHARED_POLICY]
    policy += [{"title": t, "body": b, "verify": True, "sources": ["nia"]} for t, b in extra_policy]
    data = {
        "code": code, "country": country, "region": region,
        "service_language": lang, "lang_short": lang_short,
        "language": {
            "intro": f"主要服务语言：{lang}。"
                     + ("华语客人较多，可先用中文确认，再切换。" if code in ("SG", "MY") else "客人若英语流利，可直接用英语沟通。" if lang != "英语" and code in ("IN", "SA") else ""),
            "phrases": ph,
        },
        "culture": [{"title": t, "body": b} for t, b in culture],
        "policy": policy,
        "customs": [{"title": t, "body": b} for t, b in customs],
        "sources": sources,
    }
    (OUT / f"{code}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
print("written", len(M), "markets")
