from dataclasses import dataclass
import threading
import fabric
import os
import re

@dataclass
class MikroTikSSHDevice:

    def __post_init__(self):
        self.interfaces = {}
        for i in os.environ["MIKROTIK_INTERFACES"].split(";"):
            self.interfaces.__setitem__(*i.split(","))
        self.is_being_polled = threading.Event()
        self.interface_groups_cache = {}

        self.interface_groups = []
        temp = []
        for i, interface_name in enumerate(self.interfaces.keys(), 1):
            temp.append(interface_name)
            if i % 4 == 0:
                self.interface_groups.append(tuple(temp))
                temp = []
        
        # make sure we have some cache
        # also use as sanity-test
        for interface_group in self.interface_groups:
            self._poll_interface_group(interface_group)

    def _get_conn(self):
        return fabric.Connection(
            user = os.environ["MIKROTIK_USER"],
            host = os.environ["MIKROTIK_DEVICE"],
            connect_kwargs = {"key_filename": os.environ["MIKROTIK_KEY_PATH"]}
        )

    def _get_interfacegroup_containing(self, interface_name):
        for interface_group in self.interface_groups:
            if interface_name in interface_group:
                return interface_group

    def _poll_interface_group(self, interface_group):
        self.is_being_polled.set()
        result = self._get_conn().run("/interface/ethernet/poe/monitor %s once" % ",".join(interface_group), hide = True)
        self.is_being_polled.clear()
        parsed_result = self._parse_result(result)
        self.interface_groups_cache[interface_group] = parsed_result
        # print("Cached group:", interface_group)
        return parsed_result

    def _parse_result(self, result):
        r = result.stdout
        # print(r)
        s = [re.split(r" +", row.rstrip())[1:] for row in r.split("\r\n")][:-2]
        out = {i: {} for i in s[0][1:]}
        off_interfaces = set()
        for row in s[1:]:
            column_decrimator = 0
            output_name = row[0][:-1]
            # print(output_name)

            for i, interface_name in enumerate(out.keys(), 0):
                # print("off_interfaces:", off_interfaces)
                # print(i, interface_name, row[1:][i])
                if interface_name in off_interfaces:
                    # print("Skipping '%s' for %s..." % (output_name, interface_name))
                    column_decrimator += 1
                else:
                    out[interface_name][output_name] = row[1:][i - column_decrimator]

                if output_name == "poe-out-status":
                    if row[1:][i] != "powered-on":
                        # print("Adding %s to off interfaces" % interface_name)
                        off_interfaces.add(interface_name)
        return out

    # i refuse to use async programming
    def get_interface_poe(self, interface_name):
        interface_group = self._get_interfacegroup_containing(interface_name)
        if self.is_being_polled.is_set():
            result = self.interface_groups_cache[interface_group][interface_name]
            result["cached"] = True
        else:
            result = self._poll_interface_group(interface_group)[interface_name]
            result["cached"] = False
        
        return result

if __name__ == "__main__":
    if not os.path.exists(os.path.join("/app", ".docker")):
        import dotenv
        dotenv.load_dotenv(dotenv_path = "power.env")

    import time
    mikrotik = MikroTikSSHDevice()
    print("Ready.")
    for interface_name in mikrotik.interfaces.keys():
        threading.Thread(target = lambda i: print(i, mikrotik.get_interface_poe(i)), args = (interface_name, )).start()
        time.sleep(1)