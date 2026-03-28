package com.ved.cleannet

import org.junit.Test

import org.junit.Assert.*

/**
 * Example local unit test, which will execute on the development machine (host).
 *
 * See [testing documentation](http://d.android.com/tools/testing).
 */
class ExampleUnitTest {
    @Test
    fun addition_isCorrect() {
        assertEquals(4, 2 + 2)
    }

    @Test
    fun blocklist_parses_plain_domain() {
        assertEquals("evil.com", Blocklist.parseLine("  Evil.COM  "))
    }

    @Test
    fun blocklist_parses_hosts_line() {
        assertEquals("bad.example", Blocklist.parseLine("0.0.0.0 bad.example"))
    }

    @Test
    fun blocklist_ignores_comments() {
        assertNull(Blocklist.parseLine("# evil.com"))
        assertEquals("ok.test", Blocklist.parseLine("ok.test # trailing"))
    }
}