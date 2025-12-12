/**
 * Dorsal Report Default Script
 * Handles basic interactivity for the HTML report.
 */
document.addEventListener('DOMContentLoaded', function () {
    // --- Toast Message Handler ---
    let toastTimeout;
    function showToast(message) {
        const toast = document.getElementById('toast');
        if (!toast) return;

        toast.textContent = message;
        toast.classList.add('show');
        clearTimeout(toastTimeout);
        toastTimeout = setTimeout(() => {
            toast.classList.remove('show');
        }, 2000);
    }

    // --- Event Delegation for Dynamic Elements ---
    document.body.addEventListener('click', function (event) {
        // Accordion handler
        const accordionHeader = event.target.closest('.accordion-header');
        if (accordionHeader) {
            const content = accordionHeader.nextElementSibling;
            const icon = accordionHeader.querySelector('.accordion-icon');
            const isVisible = content.style.display === 'block';

            content.style.display = isVisible ? 'none' : 'block';
            if(icon) icon.style.transform = isVisible ? 'rotate(0deg)' : 'rotate(180deg)';
        }

        // Hash copy icon handler
        const copyIcon = event.target.closest('.copy-icon');
        if (copyIcon) {
            const hashText = copyIcon.previousElementSibling.textContent;
            navigator.clipboard.writeText(hashText).then(() => {
                showToast('Copied to clipboard!');
            }).catch(err => {
                console.error('Failed to copy hash: ', err);
                showToast('Failed to copy!');
            });
        }

        // Hash click-to-select handler
        const hashValue = event.target.closest('.hash-value');
        if (hashValue) {
            const selection = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(hashValue);
            selection.removeAllRanges();
            selection.addRange(range);
        }
    });

    // --- Tab handler (on initial load) ---
    const tabs = document.querySelectorAll('.tab-link');
    const tabContents = document.querySelectorAll('.tab-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const target = document.querySelector(tab.dataset.target);
            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            target.classList.add('active');
        });
    });

    // --- Light/Dark mode handler ---
    const themeToggle = document.getElementById('theme-toggle');
    const root = document.documentElement;
    if (localStorage.getItem('theme') === 'dark' ||
       (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        root.classList.add('dark');
    } else {
        root.classList.remove('dark');
    }
    if (themeToggle) {
        themeToggle.addEventListener('click', function() {
            const isDark = root.classList.toggle('dark');
            localStorage.setItem('theme', isDark ? 'dark' : 'light');
        });
    }

    // --- Generic toggle handler for dates and file size ---
    const genericToggles = document.querySelectorAll('[data-toggle="value"]');
    genericToggles.forEach(el => {
        el.addEventListener('click', () => {
            const currentText = el.textContent;
            const humanValue = el.getAttribute('data-human');
            const rawValue = el.getAttribute('data-raw');
            el.textContent = currentText === humanValue ? rawValue : humanValue;
        });
        el.style.cursor = 'pointer';
        el.setAttribute('title', 'Click to toggle format');
    });
});