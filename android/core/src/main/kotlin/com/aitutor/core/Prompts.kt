package com.aitutor.core

// Transcription prompts ported verbatim from the web build
// (server/aitutor_server/gemini/transcriber.py). The large grader system
// prompts (grader_{en,zh}.md) are NOT inlined here -- the Android layer loads
// them from assets and passes the text to chatPrompt(), so they stay
// single-sourced with the web build.

object Prompts {

    val QUESTION_EN = """
        You are looking at a PSLE Primary 6 English Continuous Writing question prompt.
        The page contains some combination of: printed instructions, a question or
        topic statement, and 3-4 illustrated picture stimuli the student must use in
        their composition.

        Output two clearly delimited sections:

        === Prompt ===
        Verbatim transcription of ALL printed text on the page (instructions,
        question, any captions). Preserve the original line structure as much as
        possible. Do NOT paraphrase. If the page has no printed text, write "(none)".

        === Pictures ===
        For each illustrated panel, in order:
        - Identify the setting (where it takes place).
        - Identify the main characters and any relevant objects.
        - Describe what is happening in clear, specific terms.
        - Note any text, signs, or labels visible inside the illustration itself.
        Output as a numbered list, one short paragraph per panel. If there are no
        illustrated panels, write "(none)".

        Be factual and concise. Do not invent details that are not depicted.
    """.trimIndent()

    val QUESTION_ZH = """
        这是 PSLE 小六华文作文的题目页。页面通常包含印刷的题目说明、作文要求，
        以及 5-6 幅按顺序排列的插图（看图作文）。

        请输出两个用分隔线明确分开的部分：

        === 题目 ===
        逐字转录页面上所有印刷的文字（说明、题目、任何说明文字）。尽量保留原本的
        排版结构。不要意译或概括。如果页面没有印刷文字，请写 "(无)"。

        === 图片 ===
        按顺序描述每一幅插图：
        - 说明场景（地点、时间）。
        - 指出主要人物和重要物件。
        - 用具体的语言描述正在发生的事情。
        - 如果插图里有文字、招牌或对话泡泡，请逐字记录。
        用编号列表输出，每幅图一段。如果没有插图，请写 "(无)"。

        请客观、简洁地描述，不要编造图中没有的内容。
    """.trimIndent()

    val ESSAY_EN = """
        Transcribe the handwritten English text in this image VERBATIM.

        Rules:
        - Output only the transcribed text. No commentary, no analysis, no headers.
        - Preserve line breaks as they appear on the page.
        - Preserve the student's spelling exactly, including any spelling mistakes.
        - Preserve the student's punctuation exactly.
        - If a word is illegible, write [?] in its place.
        - Do not include lined-paper rules, page numbers, or printed labels.
    """.trimIndent()

    val ESSAY_ZH = """
        请逐字转录图片中的手写华文。

        规则：
        - 只输出转录的文字，不要任何注释、分析或标题。
        - 严格保留原文的换行。
        - 严格保留学生的写法（包括错别字），不要替学生改正。
        - 严格保留学生的标点符号。
        - 如果某个字看不清楚，请用 [?] 代替。
        - 不要包括稿纸的格线、页码或印刷的标签。
    """.trimIndent()

    fun essayPrompt(language: String): String =
        if (language == "zh-Hans") ESSAY_ZH else ESSAY_EN

    fun questionPrompt(language: String): String =
        if (language == "zh-Hans") QUESTION_ZH else QUESTION_EN

    /** Builds the grader user turn (ported from grader._user_prompt). */
    fun graderUser(req: GradeRequest): String {
        if (req.language == "zh-Hans") {
            return "题目：\n${req.questionText}\n\n" +
                "学生作文：\n${req.essayText}\n\n" +
                "请按照评分细则评分，并按指定的 JSON 格式输出。"
        }
        val paper = if (req.paperType == "continuous")
            "Continuous Writing (36 marks)" else "Situational Writing (14 marks)"
        return "Paper: PSLE English Paper 1 - $paper\n\n" +
            "Question:\n${req.questionText}\n\n" +
            "Student's essay:\n${req.essayText}\n\n" +
            "Mark this essay against the rubric. Output JSON only."
    }

    /** Qwen3.5 (ChatML) prompt. The vision job injects the image via libmtmd
     *  ahead of the prompt text; grading is text-only. */
    fun chatPrompt(system: String, user: String): String =
        "<|im_start|>system\n${system.trim()}<|im_end|>\n" +
            "<|im_start|>user\n${user.trim()}<|im_end|>\n" +
            "<|im_start|>assistant\n"
}
