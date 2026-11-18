const steps = [
  { title: '画像自测', goal: '先建立你的八维能力画像', video: './media/01-profile.mp4', poster: './media/01-profile.jpg', actions: ['在首页点击「画像」。新账号先点右上角「新建用户」。', '按顺序完成测评题，选择答案后系统自动进入下一题。', '提交后查看八维能力画像和学习建议，再进入学习地图。'] },
  { title: '个性化学习', goal: '让系统按你的薄弱点生成学习材料', video: './media/02-learning.mp4', poster: './media/02-learning.jpg', actions: ['打开「学习地图」，点击当前要补强的技能点。', '在技能点对话工作台输入问题，等待司南教学 Agent 生成讲义、学习报告或实操指南。', '打开生成资源阅读，结束后回到对应技能点或实战记录继续复习。'] },
  { title: '动态做题', goal: '根据答题表现实时升降难度', video: './media/03-quiz.mp4', poster: './media/03-quiz.jpg', actions: ['在技能点页面进入做题。', '逐题选择答案；连续答对会升档，答错会降档。', '完成本轮后查看正确率和薄弱点，再继续下一轮。'] },
  { title: '接单与首呼', goal: '抢下订单并确认客户需求', video: './media/04-order.mp4', poster: './media/04-order.jpg', actions: ['打开「消息中心」，刷新订单，在倒计时内点击抢单。', '抢单后进入「订单管理」，按右下角导航提示点击「首呼」。', '与客户确认称呼、客源地、人数、日期和需求，并填写需求确认单。'] },
  { title: '行前方案与报价', goal: '询价、做方案、报价并完成交付', video: './media/05-prepare.mp4', poster: './media/05-prepare.jpg', actions: ['在资源群向地接社、酒店、车队、票务询价并确认价格。', '创建行程方案发送给客户，按反馈修改，再填写成本、利润和分项报价。', '客户确认后提交合同、保险和出团通知书。'] },
  { title: '行中应急处理', goal: '按正确处理顺序解决突发事件', video: './media/06-incident.mp4', poster: './media/06-incident.jpg', actions: ['收到突发事件后，进入对应工作群。', '先安抚客户，再联系地接、车队或酒店给出替代方案。', '问题解决后在群内确认结果，等待系统评分。'] },
  { title: '行后结算与复盘', goal: '核对结算、查看评分并更新画像', video: './media/07-settlement.mp4', poster: './media/07-settlement.jpg', actions: ['进入「成本与结算」，逐项核对地接结算单和实际成本。', '处理赔偿或追偿，完成结账留档并检查实际利润。', '到「订单评分」查看 61 技能点分数和证据，再到「学情画像」更新画像。'] }
];

const video = document.querySelector('#step-video');
const source = video.querySelector('source');
const stepCount = document.querySelector('#step-count');
const stepTitle = document.querySelector('#step-title');
const stepGoal = document.querySelector('#step-goal');
const stepList = document.querySelector('#step-list');
const card = document.querySelector('.manual-card');
const dots = document.querySelector('#dots');
const prevButton = document.querySelector('#prev');
const nextButton = document.querySelector('#next');
const prevText = document.querySelector('#prev-text');
const nextText = document.querySelector('#next-text');
const stage = document.querySelector('#video-stage');
let current = 0;
let startX = 0;
let startY = 0;

const buttons = steps.map((step, index) => {
  const button = document.createElement('button');
  button.className = 'dot';
  button.type = 'button';
  button.setAttribute('aria-label', `跳到第 ${index + 1} 步：${step.title}`);
  button.addEventListener('click', () => goTo(index));
  dots.appendChild(button);
  return button;
});

function render(index) {
  const step = steps[index];
  stepCount.textContent = `第 ${String(index + 1).padStart(2, '0')} 步 / 共 ${String(steps.length).padStart(2, '0')} 步`;
  stepTitle.textContent = step.title;
  stepGoal.textContent = step.goal;
  stepList.replaceChildren(...step.actions.map((action) => {
    const item = document.createElement('li');
    item.textContent = action;
    return item;
  }));
  buttons.forEach((button, dotIndex) => button.classList.toggle('is-active', dotIndex === index));
  source.src = step.video;
  video.poster = step.poster;
  video.load();
  video.play().catch(() => {});
  card.classList.remove('is-switching');
  void card.offsetWidth;
  card.classList.add('is-switching');
}

function goTo(index) {
  current = (index + steps.length) % steps.length;
  render(current);
}

prevButton.addEventListener('click', () => goTo(current - 1));
nextButton.addEventListener('click', () => goTo(current + 1));
prevText.addEventListener('click', () => goTo(current - 1));
nextText.addEventListener('click', () => goTo(current + 1));

stage.addEventListener('pointerdown', (event) => { startX = event.clientX; startY = event.clientY; });
stage.addEventListener('pointerup', (event) => {
  const deltaX = event.clientX - startX;
  const deltaY = event.clientY - startY;
  if (Math.abs(deltaX) > 60 && Math.abs(deltaX) > Math.abs(deltaY)) goTo(current + (deltaX < 0 ? 1 : -1));
});

window.addEventListener('keydown', (event) => {
  if (event.key === 'ArrowLeft') goTo(current - 1);
  if (event.key === 'ArrowRight') goTo(current + 1);
});

render(current);
