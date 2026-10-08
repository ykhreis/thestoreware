document.addEventListener("DOMContentLoaded", () => {

    // Reveal sections smoothly while scrolling
    const revealItems = document.querySelectorAll(".reveal");

    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add("visible");
                observer.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.12
    });

    revealItems.forEach((item) => {
        observer.observe(item);
    });


    // Feedback rating buttons
    document.querySelectorAll(".rating button").forEach((button) => {

        button.addEventListener("click", () => {

            document.querySelectorAll(".rating button").forEach((b) => {
                b.classList.remove("selected");
            });

            button.classList.add("selected");

        });

    });


    // Temporary feedback button behaviour
    const feedbackButton = document.querySelector(".feedback-submit");

    if (feedbackButton) {

        feedbackButton.addEventListener("click", () => {

            const note = document.querySelector(".feedback-note");

            if (note) {
                note.textContent =
                    "Thank you. Feedback storage will be connected during the testing phase.";
            }

        });

    }

});