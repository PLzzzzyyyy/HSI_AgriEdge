"""XSCT build acceptance checks; vendor commands are stubbed, Tcl script is real."""
import pathlib
import tempfile
import tkinter
import unittest

SCRIPT = pathlib.Path(__file__).with_name('build_periph_app.tcl')


class BuildAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        (self.root / 'tools').mkdir()
        self.script = self.root / 'tools/build_periph_app.tcl'
        self.script.write_bytes(SCRIPT.read_bytes())
        src = self.root / 'src/ps/periph'
        src.mkdir(parents=True)
        (src / 'periph_main.cpp').write_text('int main() { return 0; }')
        (src / 'periph.h').write_text('#pragma once')
        self.ws = self.root / 'workspace'
        (self.ws / 'periph_plat').mkdir(parents=True)
        board = self.root / 'board/periph'
        board.mkdir(parents=True)
        self.old = board / 'periph_zu5ev.elf'
        self.old.write_bytes(b'legacy ELF')
        self.tcl = tkinter.Tcl()
        self.tcl.setvar('argv', (self.ws.as_posix(),))
        self.tcl.setvar('env(XILINX_VITIS)', (self.root / 'vitis').as_posix())
        self.tcl.eval('''
            set compiler_flags {}
            set make_output {aarch64-none-elf-g++ compile and link}
            set make_fail 0
            set xsct_fail 0
            proc setws {args} {}
            proc importsources {args} {}
            proc app {subcmd args} {
                global ws app compiler_flags xsct_fail
                if {$subcmd eq "config"} { lappend compiler_flags {*}$args }
                if {$subcmd eq "build"} {
                    if {$xsct_fail} { error "XSCT build failed" }
                    file mkdir $ws/$app/Release
                    set f [open $ws/$app/Release/$app.elf w]
                    puts -nonewline $f {new ELF}
                    close $f
                }
                return {}
            }
            rename exec real_exec
            proc exec {args} {
                global make_output make_fail
                if {$make_fail} { error $make_output }
                return $make_output
            }
        ''')

    def run_script(self):
        return self.tcl.call('source', self.script.as_posix())

    def test_enforces_compiler_werror(self):
        self.run_script()
        self.assertIn('-Werror', self.tcl.eval('set compiler_flags'))

    def test_rejects_real_warning_despite_empty_app_return(self):
        self.tcl.setvar('make_output', 'periph_main.cpp: warning: test warning')
        with self.assertRaises(tkinter.TclError):
            self.run_script()
        self.assertEqual(self.old.read_bytes(), b'legacy ELF')

    def test_rejects_make_failure_with_existing_elf(self):
        self.tcl.setvar('make_fail', 1)
        self.tcl.setvar('make_output', 'make: *** compilation failed')
        with self.assertRaises(tkinter.TclError):
            self.run_script()
        self.assertEqual(self.old.read_bytes(), b'legacy ELF')

    def test_requires_xsct_build_success(self):
        self.tcl.setvar('xsct_fail', 1)
        with self.assertRaises(tkinter.TclError):
            self.run_script()
        self.assertEqual(self.old.read_bytes(), b'legacy ELF')

    def test_preserves_compiler_log_and_legacy_elf(self):
        self.run_script()
        log = self.ws / 'periph_zu5ev/application_build.log'
        self.assertTrue(log.is_file(), 'real compiler output must be saved')
        self.assertIn('compile and link', log.read_text())
        self.assertEqual(self.old.read_bytes(), b'legacy ELF')


if __name__ == '__main__':
    unittest.main(verbosity=2)
