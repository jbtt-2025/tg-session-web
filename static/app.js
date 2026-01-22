// Global state
let loginState = {
    phone: '',
    sessionId: '',
    sessionString: ''
};

let createState = {
    sessionString: '',
    tgId: null,
    notifyChatId: null
};

let verifyState = {
    eventSource: null,
    reconnectAttempts: 0,
    maxReconnectAttempts: 3,
    reconnectDelay: 2000,
    currentTaskUuid: null,
    currentSessionString: null
};

// Utility functions
function showMessage(containerId, message, type = 'info') {
    const container = document.getElementById(containerId);
    container.innerHTML = `<div class="message ${type}">${message}</div>`;
}

function clearMessage(containerId) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
}

function showElement(elementId) {
    document.getElementById(elementId).classList.remove('hidden');
}

function hideElement(elementId) {
    document.getElementById(elementId).classList.add('hidden');
}

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        const tabName = tab.dataset.tab;
        
        // Update tab buttons
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        
        // Update tab content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
        });
        document.getElementById(`${tabName}-tab`).classList.add('active');
    });
});

// ============================================
// Tab 1: Login functionality
// ============================================

document.getElementById('submit-phone').addEventListener('click', async () => {
    const phone = document.getElementById('phone').value.trim();
    
    if (!phone) {
        showMessage('login-message', '请输入手机号码', 'error');
        return;
    }
    
    loginState.phone = phone;
    const btn = document.getElementById('submit-phone');
    btn.disabled = true;
    btn.innerHTML = '发送中...<span class="loading"></span>';
    
    try {
        const response = await fetch('/api/login/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || '发送验证码失败');
        }
        
        loginState.sessionId = data.session_id;
        
        hideElement('phone-step');
        showElement('code-step');
        showMessage('login-message', '验证码已发送，请查收', 'success');
        
    } catch (error) {
        showMessage('login-message', `错误: ${error.message}`, 'error');
        btn.disabled = false;
        btn.innerHTML = '发送验证码';
    }
});

document.getElementById('submit-code').addEventListener('click', async () => {
    const code = document.getElementById('code').value.trim();
    
    if (!code) {
        showMessage('login-message', '请输入验证码', 'error');
        return;
    }
    
    const btn = document.getElementById('submit-code');
    btn.disabled = true;
    btn.innerHTML = '验证中...<span class="loading"></span>';
    
    try {
        const response = await fetch('/api/login/code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: loginState.sessionId,
                code: code
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || '验证码错误');
        }
        
        if (data.status === 'password_required') {
            hideElement('code-step');
            showElement('password-step');
            showMessage('login-message', '需要输入两步验证密码', 'info');
            btn.disabled = false;
            btn.innerHTML = '提交验证码';
        } else if (data.status === 'success') {
            loginState.sessionString = data.session_string;
            displayLoginSuccess(data.session_string);
        }
        
    } catch (error) {
        showMessage('login-message', `错误: ${error.message}`, 'error');
        btn.disabled = false;
        btn.innerHTML = '提交验证码';
    }
});

document.getElementById('submit-password').addEventListener('click', async () => {
    const password = document.getElementById('password').value;
    
    if (!password) {
        showMessage('login-message', '请输入密码', 'error');
        return;
    }
    
    const btn = document.getElementById('submit-password');
    btn.disabled = true;
    btn.innerHTML = '验证中...<span class="loading"></span>';
    
    try {
        const response = await fetch('/api/login/password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: loginState.sessionId,
                password: password
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || '密码错误');
        }
        
        loginState.sessionString = data.session_string;
        displayLoginSuccess(data.session_string);
        
    } catch (error) {
        showMessage('login-message', `错误: ${error.message}`, 'error');
        btn.disabled = false;
        btn.innerHTML = '提交密码';
    }
});

function displayLoginSuccess(sessionString) {
    hideElement('phone-step');
    hideElement('code-step');
    hideElement('password-step');
    showElement('session-result');
    
    document.getElementById('session-string-display').textContent = sessionString;
    clearMessage('login-message');
}

document.getElementById('goto-create').addEventListener('click', () => {
    // Switch to create tab
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelector('[data-tab="create"]').classList.add('active');
    
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    document.getElementById('create-tab').classList.add('active');
    
    // Pre-fill session string
    document.getElementById('session-string').value = loginState.sessionString;
});

// Copy session button
document.getElementById('copy-session').addEventListener('click', async () => {
    const sessionString = loginState.sessionString;
    const btn = document.getElementById('copy-session');
    
    try {
        await navigator.clipboard.writeText(sessionString);
        const originalText = btn.innerHTML;
        btn.innerHTML = '✅ 已复制！';
        setTimeout(() => {
            btn.innerHTML = originalText;
        }, 2000);
    } catch (error) {
        // Fallback for older browsers
        const textarea = document.createElement('textarea');
        textarea.value = sessionString;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            const originalText = btn.innerHTML;
            btn.innerHTML = '✅ 已复制！';
            setTimeout(() => {
                btn.innerHTML = originalText;
            }, 2000);
        } catch (err) {
            showMessage('login-message', '复制失败，请手动复制', 'error');
        }
        document.body.removeChild(textarea);
    }
});

// ============================================
// Tab 2: Create Task functionality
// ============================================

document.getElementById('validate-session').addEventListener('click', async () => {
    const sessionString = document.getElementById('session-string').value.trim();
    
    if (!sessionString) {
        showMessage('create-message', '请输入 StringSession', 'error');
        return;
    }
    
    const btn = document.getElementById('validate-session');
    btn.disabled = true;
    btn.innerHTML = '验证中...<span class="loading"></span>';
    
    try {
        const response = await fetch('/api/task/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_string: sessionString })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Session 验证失败');
        }
        
        createState.sessionString = sessionString;
        createState.tgId = data.tg_id;
        createState.notifyChatId = data.tg_id; // Default to same ID
        
        displayAccountInfo(data);
        
    } catch (error) {
        showMessage('create-message', `错误: ${error.message}`, 'error');
        btn.disabled = false;
        btn.innerHTML = '验证 Session';
    }
});

function displayAccountInfo(data) {
    hideElement('validate-step');
    showElement('account-info');
    
    document.getElementById('tg-id-display').textContent = data.tg_id;
    document.getElementById('session-string-confirm').textContent = createState.sessionString;
    document.getElementById('notify-chat-id').value = data.tg_id;
    
    // Display bot name with @ prefix
    const botName = data.bot_name || '';
    const displayName = botName.startsWith('@') ? botName : `@${botName}`;
    document.getElementById('bot-name-display').textContent = displayName || '@your_bot';
    
    clearMessage('create-message');
}

document.getElementById('show-help').addEventListener('click', () => {
    document.getElementById('help-modal').classList.add('active');
});

document.getElementById('close-modal').addEventListener('click', () => {
    document.getElementById('help-modal').classList.remove('active');
});

// Close modal when clicking outside
document.getElementById('help-modal').addEventListener('click', (e) => {
    if (e.target.id === 'help-modal') {
        document.getElementById('help-modal').classList.remove('active');
    }
});

document.getElementById('create-task').addEventListener('click', async () => {
    const notifyChatId = document.getElementById('notify-chat-id').value.trim();
    
    if (!notifyChatId) {
        showMessage('create-message', '请输入通知接收者 ID', 'error');
        return;
    }
    
    const btn = document.getElementById('create-task');
    btn.disabled = true;
    btn.innerHTML = '创建中...<span class="loading"></span>';
    
    try {
        const response = await fetch('/api/task/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_string: createState.sessionString,
                notify_chat_id: parseInt(notifyChatId)
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || '创建任务失败');
        }
        
        displayTaskResult(data);
        
    } catch (error) {
        showMessage('create-message', `错误: ${error.message}`, 'error');
        btn.disabled = false;
        btn.innerHTML = '创建保活任务';
    }
});

function displayTaskResult(data) {
    hideElement('account-info');
    showElement('task-result');
    
    const verifyUrl = `${window.location.origin}/verifyCode/${data.uuid}`;
    const linkElement = document.getElementById('verify-url');
    linkElement.href = verifyUrl;
    linkElement.textContent = verifyUrl;
    
    showMessage('create-message', '任务创建成功！', 'success');
}

// ============================================
// Tab 3: Verify Code functionality (SSE)
// ============================================

document.getElementById('start-listen').addEventListener('click', () => {
    const sessionString = document.getElementById('verify-session-string').value.trim();
    
    if (!sessionString) {
        showMessage('verify-message', '请输入 StringSession', 'error');
        return;
    }
    
    startListening(sessionString);
});

document.getElementById('start-listen-task').addEventListener('click', () => {
    if (verifyState.currentSessionString) {
        startListening(verifyState.currentSessionString);
    }
});

document.getElementById('cancel-listen').addEventListener('click', () => {
    stopListening();
    hideElement('verify-waiting');
    
    if (verifyState.currentTaskUuid) {
        showElement('verify-task-info');
    } else {
        showElement('verify-input-step');
    }
    
    clearMessage('verify-message');
});

document.getElementById('listen-again').addEventListener('click', () => {
    hideElement('verify-result');
    
    if (verifyState.currentTaskUuid) {
        showElement('verify-task-info');
    } else {
        showElement('verify-input-step');
    }
    
    clearMessage('verify-message');
});

document.getElementById('delete-task').addEventListener('click', async () => {
    if (!verifyState.currentTaskUuid) {
        return;
    }
    
    if (!confirm('确定要删除此保活任务吗？此操作不可恢复。')) {
        return;
    }
    
    const btn = document.getElementById('delete-task');
    btn.disabled = true;
    btn.innerHTML = '删除中...<span class="loading"></span>';
    
    try {
        const response = await fetch(`/api/task/${verifyState.currentTaskUuid}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || '删除任务失败');
        }
        
        showMessage('verify-message', '任务已成功删除', 'success');
        
        // Reset state and show input step
        verifyState.currentTaskUuid = null;
        verifyState.currentSessionString = null;
        hideElement('verify-task-info');
        showElement('verify-input-step');
        
    } catch (error) {
        showMessage('verify-message', `错误: ${error.message}`, 'error');
        btn.disabled = false;
        btn.innerHTML = '🗑️ 删除此任务';
    }
});

function startListening(sessionString) {
    hideElement('verify-input-step');
    hideElement('verify-result');
    hideElement('verify-task-info');
    showElement('verify-waiting');
    clearMessage('verify-message');
    
    document.getElementById('elapsed-time').textContent = '0';
    
    connectSSE(sessionString);
}

function connectSSE(sessionString) {
    const url = `/api/verify/listen?session_string=${encodeURIComponent(sessionString)}`;
    verifyState.eventSource = new EventSource(url);
    
    verifyState.eventSource.addEventListener('connected', (e) => {
        console.log('Connected, waiting for code...');
        verifyState.reconnectAttempts = 0;
    });
    
    verifyState.eventSource.addEventListener('code', (e) => {
        const data = JSON.parse(e.data);
        displayVerificationCode(data.code);
        stopListening();
    });
    
    verifyState.eventSource.addEventListener('heartbeat', (e) => {
        const data = JSON.parse(e.data);
        document.getElementById('elapsed-time').textContent = data.elapsed;
    });
    
    verifyState.eventSource.addEventListener('timeout', (e) => {
        showMessage('verify-message', '等待验证码超时（5分钟）', 'error');
        stopListening();
        hideElement('verify-waiting');
        showElement('verify-input-step');
    });
    
    verifyState.eventSource.addEventListener('error', (e) => {
        try {
            const data = JSON.parse(e.data);
            showMessage('verify-message', `错误: ${data.error}`, 'error');
        } catch {
            console.error('SSE connection error');
        }
        
        stopListening();
        
        // Auto-reconnect logic
        if (verifyState.reconnectAttempts < verifyState.maxReconnectAttempts) {
            verifyState.reconnectAttempts++;
            console.log(`Reconnecting... (${verifyState.reconnectAttempts}/${verifyState.maxReconnectAttempts})`);
            showMessage('verify-message', `连接断开，正在重连... (${verifyState.reconnectAttempts}/${verifyState.maxReconnectAttempts})`, 'info');
            setTimeout(() => connectSSE(sessionString), verifyState.reconnectDelay);
        } else {
            showMessage('verify-message', '连接失败，请重试', 'error');
            hideElement('verify-waiting');
            showElement('verify-input-step');
        }
    });
    
    verifyState.eventSource.onerror = (error) => {
        console.error('SSE onerror:', error);
        // The 'error' event handler above will handle reconnection
    };
}

function stopListening() {
    if (verifyState.eventSource) {
        verifyState.eventSource.close();
        verifyState.eventSource = null;
    }
    verifyState.reconnectAttempts = 0;
}

function displayVerificationCode(code) {
    hideElement('verify-waiting');
    showElement('verify-result');
    
    document.getElementById('code-display').textContent = code;
    showMessage('verify-message', '验证码接收成功！', 'success');
}

// Initialize
console.log('Telegram Session Manager initialized');

// Check for UUID parameter in URL (from /verifyCode/{uuid} redirect)
const urlParams = new URLSearchParams(window.location.search);
const uuid = urlParams.get('uuid');

if (uuid) {
    // Switch to verify tab
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelector('[data-tab="verify"]').classList.add('active');
    
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    document.getElementById('verify-tab').classList.add('active');
    
    // Load task info
    loadTaskInfo(uuid);
}

async function loadTaskInfo(uuid) {
    showMessage('verify-message', '正在加载任务信息...', 'info');
    
    try {
        const response = await fetch(`/api/task/${uuid}`);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || '加载任务失败');
        }
        
        // Store task info
        verifyState.currentTaskUuid = uuid;
        verifyState.currentSessionString = data.session_string;
        
        // Display task info
        hideElement('verify-input-step');
        showElement('verify-task-info');
        
        document.getElementById('task-uuid-display').textContent = uuid;
        document.getElementById('task-tg-id-display').textContent = data.tg_id || 'N/A';
        
        clearMessage('verify-message');
        showMessage('verify-message', '任务信息加载成功，点击按钮开始监听验证码', 'success');
        
    } catch (error) {
        showMessage('verify-message', `错误: ${error.message}`, 'error');
    }
}
