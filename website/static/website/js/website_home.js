document.addEventListener("DOMContentLoaded", () => {
    const revealElements = document.querySelectorAll(".reveal");

    // Fallback: if IntersectionObserver is unavailable,
    // show all elements immediately.
    if (!("IntersectionObserver" in window)) {
        revealElements.forEach((el) => {
            el.classList.add("visible");
        });
        return;
    }

    const observer = new IntersectionObserver(
        (entries, obs) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add("visible");
                    obs.unobserve(entry.target);
                }
            });
        },
        {
            threshold: 0.08,
            rootMargin: "0px 0px -30px 0px",
        }
    );

    revealElements.forEach((el) => {
        observer.observe(el);
    });
});