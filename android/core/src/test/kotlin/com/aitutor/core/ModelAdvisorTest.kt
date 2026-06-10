package com.aitutor.core

import kotlin.test.Test
import kotlin.test.assertEquals

class ModelAdvisorTest {

    private fun gib(n: Double): Long = (n * 1024 * 1024 * 1024).toLong()

    @Test
    fun lowRamGetsTwoB() {
        // Z Flip 5: 8 GB nominal reports ~7.4 GiB.
        assertEquals(ModelChoice.QWEN_2B, ModelAdvisor.recommend(gib(7.4)))
        assertEquals(ModelChoice.QWEN_2B, ModelAdvisor.recommend(gib(6.0)))
        // A 10 GB device (reports ~9.x) still gets 2B.
        assertEquals(ModelChoice.QWEN_2B, ModelAdvisor.recommend(gib(9.3)))
    }

    @Test
    fun twelveGbClassGetsFourB() {
        // A 12 GB phone reports ~11.3 GiB -> must classify as 4B.
        assertEquals(ModelChoice.QWEN_4B, ModelAdvisor.recommend(gib(11.3)))
        assertEquals(ModelChoice.QWEN_4B, ModelAdvisor.recommend(gib(16.0)))
    }

    @Test
    fun boundaryIsInclusive() {
        assertEquals(ModelChoice.QWEN_4B, ModelAdvisor.recommend(ModelAdvisor.HIGH_RAM_THRESHOLD_BYTES))
        assertEquals(ModelChoice.QWEN_2B, ModelAdvisor.recommend(ModelAdvisor.HIGH_RAM_THRESHOLD_BYTES - 1))
    }
}
