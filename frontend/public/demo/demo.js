const steps = [
  { title: '画像自测', goal: '先建立你的八维能力画像', video: './media/01-profile.mp4', poster: './media/01-profile.jpg', actions: ['在首页点击「画像」。新账号先点右上角「新建用户」。', '按顺序完成测评题，选择答案后系统自动进入下一题。', '提交后查看八维能力画像和学习建议，再进入学习地图。'] },
  { title: '个性化学习', goal: '让系统按你的薄弱点生成学习材料', video: './media/02-learning.mp4', poster: './media/02-learning.jpg', actions: ['打开「学习地图」，点击当前要补强的技能点。', '在技能点对话工作台输入问题，等待司南教学 Agent 生成讲义、学习报告或实操指南。', '打开生成资源阅读，结束后回到对应技能点或实战记录继续复习。'] },
  { title: '动态做题', goal: '根据答题表现实时升降难度', video: './media/03-quiz.mp4', poster: './media/03-quiz.jpg', actions: ['在技能点页面进入做题。', '逐题选择答案；连续答对会升档，答错会降档。', '完成本轮后查看正确率和薄弱点，再继续下一轮。'] },
  { title: '接单与首呼', goal: '抢下订单并确认客户需求', video: './media/04-order.mp4', poster: './media/04-order.jpg', actions: ['打开「消息中心」，刷新订单，在倒计时内点击抢单。', '抢单后进入「订单管理」，按右下角导航提示点击「首呼」。', '与客户确认称呼、客源地、人数、日期和需求，并填写需求确认单。'] },
  { title: '行前方案与报价', goal: '询价、做方案、报价并完成交付', video: './media/05-prepare.mp4', poster: './media/05-prepare.jpg', actions: ['在资源群向地接社、酒店、车队、票务询价并确认价格。', '创建行程方案发送给客户，按反馈修改，再填写成本、利润和分项报价。', '客户确认后提交合同、保险和出团通知书。'] },
  { title: '行中应急处理', goal: '按正确处理顺序解决突发事件', video: './media/06-incident.mp4', poster: './media/06-incident.jpg', actions: ['收到突发事件后，进入对应工作群。', '先安抚客户，再联系地接、车队或酒店给出替代方案。', '问题解决后在群内确认结果，等待系统评分。'] },
  { title: '行后结算与复盘', goal: '核对结算、查看评分并更新画像', video: './media/07-settlement.mp4', poster: './media/07-settlement.jpg', actions: ['进入「成本与结算」，逐项核对地接结算单和实际成本。', '处理赔偿或追偿，完成结账留档并检查实际利润。', '到「订单评分」查看 61 技能点分数和证据，再到「学情画像」更新画像。'] }
];

const track = document.querySelector('#track');
const viewport = document.querySelector('#viewport');
const prev = document.querySelector('#prev');
const next = document.querySelector('#next');
const dots = document.querySelector('#dots');
const position = document.querySelector('#position');
let current = 0;
let startX = 0;
let startY = 0;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const slides = steps.map((step, index) => {
  const slide = element('article', 'manual-slide');
  slide.setAttribute('role', 'group');
  slide.setAttribute('aria-roledescription', 'slide');
  slide.setAttribute('aria-label', `第 ${index + 1} 步：${step.title}`);

  const head = element('div', 'slide-head');
  head.append(
    element('p', 'slide-index', `${String(index + 1).padStart(2, '0')} / ${String(steps.length).padStart(2, '0')}`),
    element('h2', '', step.title),
    element('p', 'slide-goal', step.goal)
  );

  const stage = element('div', 'video-stage');
  const video = document.createElement('video');
  video.muted = true;
  video.loop = true;
  video.playsInline = true;
  video.controls = true;
  video.preload = 'none';
  video.poster = step.poster;
  video.setAttribute('aria-label', `${step.title}录屏`);
  const source = document.createElement('source');
  source.src = step.video;
  source.type = 'video/mp4';
  video.appendChild(source);
  stage.appendChild(video);

  const actions = element('div', 'actions');
  const list = element('ol', 'action-list');
  step.actions.forEach((action) => list.appendChild(element('li', '', action)));
  actions.append(element('p', 'actions-title', '这样操作'), list);

  slide.append(head, stage, actions);
  track.appendChild(slide);
  return { slide, video };
});

const dotButtons = steps.map((step, index) => {
  const dot = element('button', 'dot');
  dot.type = 'button';
  dot.setAttribute('aria-label', `跳到第 ${index + 1} 步：${step.title}`);
  dot.addEventListener('click', () => goTo(index));
  dots.appendChild(dot);
  return dot;
});

function syncState() {
  slides.forEach(({ slide }, slideIndex) => {
    const active = slideIndex === current;
    slide.setAttribute('aria-hidden', String(!active));
    if (active) slide.removeAttribute('inert');
    else slide.setAttribute('inert', '');
  });
  dotButtons.forEach((dot, dotIndex) => dot.classList.toggle('is-active', dotIndex === current));
  position.textContent = `${String(current + 1).padStart(2, '0')} / ${String(steps.length).padStart(2, '0')}`;
  prev.disabled = current === 0;
  next.disabled = current === steps.length - 1;
}

function playVideo(video) {
  video.preload = 'auto';
  const start = () => {
    try { video.currentTime = 0; } catch {}
    video.play().catch(() => {});
  };
  if (video.readyState >= 2) {
    start();
  } else {
    video.addEventListener('canplay', start, { once: true });
    video.load();
  }
}

function goTo(index) {
  const nextIndex = Math.max(0, Math.min(steps.length - 1, index));
  if (nextIndex === current) return;
  slides[current].video.pause();
  current = nextIndex;
  track.style.transform = `translate3d(-${current * 100}%, 0, 0)`;
  syncState();
  playVideo(slides[current].video);
}

prev.addEventListener('click', () => goTo(current - 1));
next.addEventListener('click', () => goTo(current + 1));

viewport.addEventListener('pointerdown', (event) => { startX = event.clientX; startY = event.clientY; });
viewport.addEventListener('pointerup', (event) => {
  const deltaX = event.clientX - startX;
  const deltaY = event.clientY - startY;
  if (Math.abs(deltaX) > 55 && Math.abs(deltaX) > Math.abs(deltaY)) goTo(current + (deltaX < 0 ? 1 : -1));
});

window.addEventListener('keydown', (event) => {
  if (event.key === 'ArrowLeft') goTo(current - 1);
  if (event.key === 'ArrowRight') goTo(current + 1);
});

syncState();
playVideo(slides[0].video);
