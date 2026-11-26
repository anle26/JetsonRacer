// Runs inside the notebook output. Widget messages use the existing Jupyter connection.
(() => {
    const panel = document.querySelector('.__PANEL_ID__');
    const deadline = Date.now() + 15000;
    function mount() {
        const root = panel || document.querySelector('.__PANEL_ID__');
        const field = root && root.querySelector('.drive-keys input');
        const events = root && root.querySelector('.drive-events input');
        const buttons = root && Array.from(root.querySelectorAll(
            '.drive-w, .drive-a, .drive-s, .drive-d'));
        if (!field || !events || buttons.length !== 4) {
            if (Date.now() < deadline) setTimeout(mount, 50);
            return;
        }
        if (field.dataset.driveMounted) return;
        field.dataset.driveMounted = '1';
        field.readOnly = true;
        let sequence = 0;
        let pointer = null;
        const pressed = new Set();
        function publish(value) {
            events.value = value;
            events.dispatchEvent(new Event('input', {bubbles: true}));
        }
        function send(action, key = '') {
            const clock = root.querySelector('[data-tick]');
            publish([++sequence, clock ? clock.dataset.tick : '0', action, key].join('|'));
        }
        function direction() {
            if (pointer) return pointer.key;
            for (const key of ['s', 'a', 'd', 'w']) {
                if (pressed.has(key)) return key;
            }
            return '';
        }
        function changed() {
            const key = direction();
            send(key ? 'press' : 'release', key);
        }
        function release() {
            if (!direction()) return;
            pressed.clear();
            pointer = null;
            send('release');
        }
        field.addEventListener('keydown', e => {
            const key = e.key.toLowerCase();
            if (e.ctrlKey || e.altKey || e.metaKey || !['w','a','s','d',' '].includes(key)) return;
            e.preventDefault();
            e.stopPropagation();
            if (field.disabled || e.repeat) return;
            if (key === ' ') {
                release();
                send('stop');
            } else {
                pressed.add(key);
                changed();
            }
        });
        field.addEventListener('keyup', e => {
            if (pressed.delete(e.key.toLowerCase())) {
                e.preventDefault();
                e.stopPropagation();
                changed();
            }
        });
        field.addEventListener('blur', release);
        for (const element of buttons) {
            const button = element.matches('button') ? element : element.querySelector('button');
            const key = ['w','a','s','d'].find(k => element.classList.contains('drive-' + k));
            button.style.touchAction = 'none';
            button.addEventListener('pointerdown', e => {
                if (button.disabled || !e.isPrimary || e.button !== 0) return;
                e.preventDefault();
                field.blur();
                button.setPointerCapture(e.pointerId);
                pointer = {id: e.pointerId, key};
                changed();
            });
            for (const event of ['pointerup','pointercancel','lostpointercapture']) {
                button.addEventListener(event, e => {
                    if (pointer && pointer.id === e.pointerId) release();
                });
            }
        }
        function visibility() { if (document.hidden) release(); }
        window.addEventListener('blur', release);
        document.addEventListener('visibilitychange', visibility);
        const interval = setInterval(() => {
            if (!root.isConnected) {
                release();
                clearInterval(interval);
                window.removeEventListener('blur', release);
                document.removeEventListener('visibilitychange', visibility);
            } else if (field.disabled || document.hidden || !document.hasFocus()) {
                release();
            } else if (direction()) {
                send('hold', direction());
            }
        }, 80);
        publish('ready');
    }
    mount();
})();
