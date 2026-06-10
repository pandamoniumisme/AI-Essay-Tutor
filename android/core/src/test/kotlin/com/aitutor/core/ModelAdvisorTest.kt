package com.aitutor.core

import kotlin.test.Test
import kotlin.test.assertEquals

class ModelAdvisorTest {

    private fun gib(n: Double): Long = (n * 1024 * 1024 * 1024).toLong()

    @Test
    fun lowRamGetsTwoB() {
        // 8 GB nominal reports ~7.4 GiB; a 10 GB device ~9.x. Both below 10.5.
        assertEquals(ModelChoice.QWEN_2B, ModelAdvisor.recommend(gib(7.4)))
        assertEquals(ModelChoice.QWEN_2B, ModelAdvisor.recommend(gib(9.3)))
        assertEquals(ModelChoice.QWEN_2B, ModelAdvisor.recommend(gib(10.0)))
    }

    @Test
    fun twelveGbClassGetsFourB() {
        // A 12 GB phone reports ~10.9 GiB -> 4B (the 10.5 cutoff).
        assertEquals(ModelChoice.QWEN_4B, ModelAdvisor.recommend(gib(10.9)))
        assertEquals(ModelChoice.QWEN_4B, ModelAdvisor.recommend(gib(16.0)))
    }

    @Test
    fun boundaryIsInclusive() {
        assertEquals(ModelChoice.QWEN_4B, ModelAdvisor.recommend(ModelAdvisor.HIGH_RAM_THRESHOLD_BYTES))
        assertEquals(ModelChoice.QWEN_2B, ModelAdvisor.recommend(ModelAdvisor.HIGH_RAM_THRESHOLD_BYTES - 1))
    }
}
