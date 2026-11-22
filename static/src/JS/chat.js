// متغيرات النظام
let messages = [];
let selectedMessageId = null;
let replyToMessageId = null;
let isTyping = false;
const username = "{{ username }}";
const socket = io();
const isClipboardSupported = navigator.clipboard && typeof navigator.clipboard.writeText === 'function';

// عناصر DOM
const chatMessages = document.getElementById('chatMessages');
const messageInput = document.getElementById('messageInput');
const attachmentBtn = document.getElementById('attachmentBtn');
const attachmentMenu = document.getElementById('attachmentMenu');
const contextMenu = document.getElementById('contextMenu');
const themeToggleBtn = document.getElementById('themeToggleBtn');
const themeStyle = document.getElementById('theme-style');
const fileUpload = document.getElementById('file-upload');
const sendSound = document.getElementById('sendSound');
const receiveSound = document.getElementById('receiveSound');

// تحميل الرسائل السابقة
fetch('/get_messages')
    .then(response => response.json())
    .then(data => {
        messages = data.messages || [];
        renderMessages();
    });

// تبديل الثيم
themeToggleBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const rootEl = document.documentElement;
    const isLight = rootEl.classList.toggle('light-theme');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
    themeToggleBtn.innerHTML = isLight ? '<i class="fas fa-sun"></i>' : '<i class="fas fa-moon"></i>';
});

// تحميل الثيم المحفوظ
const savedTheme = localStorage.getItem('theme');
if (savedTheme === 'light') {
    document.documentElement.classList.add('light-theme');
    themeToggleBtn.innerHTML = '<i class="fas fa-sun"></i>';
}

// إدارة القوائم المنبثقة
attachmentBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    attachmentMenu.style.display = attachmentMenu.style.display === 'block' ? 'none' : 'block';
});

document.addEventListener('click', function () {
    attachmentMenu.style.display = 'none';
    contextMenu.style.display = 'none';
});

// إدارة النقر الأيمن
document.addEventListener('contextmenu', function (e) {
    e.preventDefault();
    const messageElement = e.target.closest('.message, .file-attachment');
    if (messageElement) {
        selectedMessageId = messageElement.dataset.id;
        showContextMenu(e.clientX, e.clientY);
    }
});

function showContextMenu(x, y) {
    contextMenu.style.left = `${x}px`;
    contextMenu.style.top = `${y}px`;
    contextMenu.style.display = 'block';
}

// استقبال الرسائل الجديدة
socket.on('message', function (data) {
    const isCurrentUser = data.user === username;
    const timestamp = typeof data.timestamp === 'string' ? new Date(data.timestamp) : new Date();

    const message = {
        id: data.id || Date.now(),
        text: data.msg,
        msg: data.msg,
        user: data.user, // استخدام 'user' بدلاً من 'sender'
        isFile: data.isFile || false,
        fileUrl: data.fileUrl || null,
        fileName: data.fileName || null,
        fileSize: data.fileSize || null,
        fileType: data.fileType || null,
        timestamp: timestamp,
        replyTo: data.replyTo || null,
        replyText: data.replyText || null,
        replySender: data.replySender || null
    };

    messages.push(message);
    renderMessages();

    if (!isCurrentUser && receiveSound) {
        receiveSound.currentTime = 0;
        receiveSound.play().catch(e => console.log('تعذر تشغيل صوت الاستلام:', e));
    }
});

// استقبال حدث حذف الرسالة
socket.on('message_deleted', function(data) {
    const messageId = data.message_id;
    
    // تصفية الرسائل المحذوفة
    messages = messages.filter(msg => {
        if (msg.id === messageId) {
            // يمكنك إضافة أي تنبيه هنا إذا لزم الأمر
            return false;
        }
        return true;
    });
    
    // إعادة عرض الرسائل
    renderMessages();
    
    // إخفاء القائمة السياقية إذا كانت ظاهرة
    contextMenu.style.display = 'none';
});

// إرسال رسالة جديدة
function sendMessage() {
    const messageText = messageInput.value.trim();

    if (!messageText && !replyToMessageId) return;

    let replyData = null;
    if (replyToMessageId) {
        const originalMessage = messages.find(msg => msg.id == replyToMessageId);
        if (originalMessage) {
            replyData = {
                id: replyToMessageId,
                text: originalMessage.text,
                sender: originalMessage.sender
            };
        }
    }

    socket.emit('message', {
        msg: messageText,
        replyTo: replyToMessageId,
        replyText: replyData?.text,
        replySender: replyData?.sender
    });

    messageInput.value = '';
    replyToMessageId = null;
    messageInput.placeholder = 'اكتب رسالة هنا...';
}

// حذف رسالة
function deleteMessage(messageId) {
    messageId = parseInt(messageId);
    if (isNaN(messageId)) {
        showToast('معرف الرسالة غير صالح', true);
        return;
    }

    const message = messages.find(msg => msg.id === messageId);
    if (!message) {
        showToast('الرسالة غير موجودة', true);
        return;
    }

    // التحقق من صلاحية المستخدم باستخدام الحقل 'user'
    if (message.user !== username) {
        showToast('ليس لديك صلاحية حذف هذه الرسالة', true);
        return;
    }

    if (confirm('هل أنت متأكد من حذف هذه الرسالة؟')) {
        fetch('/delete_message', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ message_id: messageId })
        })
        .then(response => response.json())
        .then(data => {
            if (!data.success) {
                showToast(data.error || 'فشل في حذف الرسالة', true);
            }
        })
        .catch(error => {
            showToast('حدث خطأ أثناء محاولة الحذف', true);
            console.error('Error:', error);
        });
    }
}

function getOriginalSender(messageId) {
    const originalMsg = messages.find(m => m.id == messageId);
    return originalMsg ? (originalMsg.user || originalMsg.sender || 'مستخدم') : 'مستخدم';
}

// عرض الرسائل
function renderMessages() {
    chatMessages.innerHTML = '';

    messages.forEach(msg => {
        const message = {
            id: msg.id || Date.now(),
            text: msg.msg || msg.text || '',
            user: msg.user || 'مستخدم', // استخدام 'user' فقط
            isFile: msg.isFile || false,
            fileUrl: msg.fileUrl || null,
            fileName: msg.fileName || null,
            fileSize: msg.fileSize || null,
            fileType: msg.fileType || null,
            timestamp: msg.timestamp ? new Date(msg.timestamp) : new Date(),
            replyTo: msg.replyTo || null,
            replyText: msg.replyText || null,
            replySender: msg.replySender || null
        };

        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${message.user === username ? 'message-self' : ''}`;
        messageDiv.dataset.id = message.id;

        let replyContent = '';
        if (message.replyTo) {
            const originalMessage = messages.find(m => m.id == message.replyTo);
            let replyText = message.replyText;
            let replySender = message.replySender;

            if (originalMessage) {
                replyText = originalMessage.msg || originalMessage.text ||
                    (originalMessage.isFile ? 'ملف مرفق' : 'رسالة نصية');
                replySender = originalMessage.user || 'مستخدم';
            } else if (!replyText) {
                replyText = 'رسالة محذوفة';
                replySender = 'مستخدم';
            }

            replyContent = `
                <div class="message-reply">
                    <span class="reply-sender">${replySender}</span>
                    ${replyText.substring(0, 30) + (replyText.length > 30 ? '...' : '')}
                </div>
            `;
        }

        const timeString = formatTime(message.timestamp);

        if (message.isFile && message.fileUrl && message.fileName) {
            const fileIcon = getFileIcon(message.fileType);
            messageDiv.innerHTML = `
                ${replyContent}
                <div class="file-attachment">
                    <div class="file-icon">${fileIcon}</div>
                    <div class="file-info">
                        <div class="file-name"><a href="${message.fileUrl}" download>${message.fileName}</a></div>
                        <div class="file-meta">${timeString} • ${message.fileSize || 'غير معروف'}</div>
                    </div>
                </div>
                <div class="message-header">
                    <span class="sender-name">${message.user}</span>
                    <span class="message-time">${timeString}</span>
                    ${message.user === username ? 
                    `<button class="delete-btn" style="display:none;" onclick="deleteMessage(${message.id})">
                    <i class="fas fa-trash"></i>
                    </button>` : ''}
                </div>
            `;
        } else {
            messageDiv.innerHTML = `
                ${replyContent}
                <div class="message-content">${message.text}</div>
                <div class="message-header">
                    <span class="sender-name">${message.user}</span>
                    <span class="message-time">${timeString}</span>
                    ${message.user === username ? 
                    `<button class="delete-btn" style="display:none;" onclick="deleteMessage(${message.id})">
                    <i class="fas fa-trash"></i>
                    </button>` : ''}
                </div>
            `;
        }

        chatMessages.appendChild(messageDiv);
    });

    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// وظائف القائمة السياقية
function replyToMessage() {
    const message = messages.find(msg => msg.id == selectedMessageId);
    if (message) {
        replyToMessageId = message.id;
        const senderName = message.user || message.sender || 'مستخدم';
        const messageText = message.msg || message.text || (message.isFile ? 'ملف' : 'رسالة');
        messageInput.placeholder = `رد على: ${senderName}: ${messageText.substring(0, 20)}...`;
        messageInput.focus();
    }
    contextMenu.style.display = 'none';
}

function copyMessage() {
    const message = messages.find(msg => msg.id == selectedMessageId);
    if (message) {
        let textToCopy = message.msg || message.text || '';
        if (message.isFile) {
            textToCopy = message.fileName || '';
        }

        navigator.clipboard.writeText(textToCopy).then(() => {
            showToast('تم نسخ الرسالة بنجاح');
        }).catch(err => {
            console.error('فشل في نسخ الرسالة:', err);
            // طريقة بديلة للنسخ
            const textarea = document.createElement('textarea');
            textarea.value = textToCopy;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
            showToast('تم نسخ الرسالة');
        });
    }
    contextMenu.style.display = 'none';
}

function showDeleteConfirmation() {
    const messageId = parseInt(selectedMessageId);
    if (!isNaN(messageId)) {
        deleteMessage(messageId);
    }
    contextMenu.style.display = 'none';
}

// إدارة الملفات
fileUpload.addEventListener('change', function (e) {
    if (this.files.length > 0) {
        const file = this.files[0];
        const formData = new FormData();
        formData.append('file', file);

        fetch('/upload', {
            method: 'POST',
            body: formData
        }).then(response => {
            if (response.ok) {
                this.value = '';
            }
        });
    }
});

function attachFile() {
    fileUpload.click();
    attachmentMenu.style.display = 'none';
}

function attachImage() {
    fileUpload.accept = 'image/*';
    fileUpload.click();
    attachmentMenu.style.display = 'none';
    fileUpload.addEventListener('change', function () {
        fileUpload.accept = '';
    }, { once: true });
}

// إرسال بالإنتر
function handleKeyPress(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

// وظائف مساعدة
function getFileIcon(type) {
    const icons = {
        'pdf': '📄',
        'doc': '📝',
        'docx': '📝',
        'xls': '📊',
        'xlsx': '📊',
        'zip': '🗜️',
        'image': '🖼️',
        'default': '📁'
    };

    if (!type) return icons['default'];

    type = type.toLowerCase();
    if (type.startsWith('image')) return icons['image'];

    const ext = type.split('/').pop();
    return icons[ext] || icons['default'];
}

function formatTime(date) {
    if (!(date instanceof Date)) {
        date = new Date(date);
    }
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function showToast(message, isError = false) {
    const toast = document.createElement('div');
    toast.className = `toast-notification ${isError ? 'error' : ''}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('show');
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => {
                document.body.removeChild(toast);
            }, 300);
        }, 2000);
    }, 100);
}

// إعلام السيرفر بالاتصال
socket.emit('new_user', username);