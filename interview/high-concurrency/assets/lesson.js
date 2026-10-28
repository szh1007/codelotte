/* 高并发面试课 · 共享交互
   - 选择题：点击即判分，显示解释，可重置
   - 进度勾选：localStorage 持久化（file:// 下失败也不影响使用）
*/
(function () {
  "use strict";

  var STORE_KEY = "hc-interview-progress-v1";

  function readProgress() {
    try {
      return JSON.parse(localStorage.getItem(STORE_KEY) || "{}");
    } catch (err) {
      return {};
    }
  }

  function writeProgress(data) {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(data));
    } catch (err) {
      /* file:// 或隐私模式下可能不可用，忽略即可 */
    }
  }

  var progress = readProgress();

  function updateProgressCount() {
    var count = document.querySelectorAll("[data-progress]:checked").length;
    var total = document.querySelectorAll("[data-progress]").length;
    document.querySelectorAll("[data-progress-count]").forEach(function (el) {
      el.textContent = count + " / " + total;
    });
  }

  document.querySelectorAll("[data-progress]").forEach(function (input) {
    var id = input.getAttribute("data-progress");
    if (progress[id]) {
      input.checked = true;
    }
    input.addEventListener("change", function () {
      progress[id] = input.checked;
      writeProgress(progress);
      updateProgressCount();
    });
  });

  var resetProgress = document.querySelector("[data-progress-reset]");
  if (resetProgress) {
    resetProgress.addEventListener("click", function () {
      document.querySelectorAll("[data-progress]").forEach(function (input) {
        input.checked = false;
      });
      progress = {};
      writeProgress(progress);
      updateProgressCount();
    });
  }

  updateProgressCount();

  document.querySelectorAll("[data-quiz]").forEach(function (quiz) {
    var options = Array.prototype.slice.call(quiz.querySelectorAll(".quiz-option"));
    var feedback = quiz.querySelector(".quiz-feedback");
    var explanation = quiz.getAttribute("data-explanation") || "";
    var answered = false;

    function reset() {
      answered = false;
      options.forEach(function (option) {
        option.disabled = false;
        option.classList.remove("is-correct", "is-wrong");
      });
      if (feedback) {
        feedback.hidden = true;
        feedback.textContent = "";
        feedback.classList.remove("is-correct", "is-wrong");
      }
    }

    options.forEach(function (option) {
      option.addEventListener("click", function () {
        if (answered) {
          return;
        }
        answered = true;
        var isCorrect = option.getAttribute("data-correct") === "true";

        options.forEach(function (item) {
          item.disabled = true;
          if (item.getAttribute("data-correct") === "true") {
            item.classList.add("is-correct");
          }
        });
        if (!isCorrect) {
          option.classList.add("is-wrong");
        }

        if (feedback) {
          feedback.hidden = false;
          feedback.classList.add(isCorrect ? "is-correct" : "is-wrong");
          feedback.innerHTML =
            "<strong>" + (isCorrect ? "答对了" : "再想一步") + "</strong>" + explanation;
        }
      });
    });

    var resetButton = quiz.querySelector(".quiz-reset");
    if (resetButton) {
      resetButton.addEventListener("click", reset);
    }
  });
})();
