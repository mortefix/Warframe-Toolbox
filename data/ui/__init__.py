"""The PySide6 front end.

Runs alongside the Tk one during the migration; `Warframe Toolbox.pyw --qt`
(or `WFTOOLBOX_UI=qt`) picks it. Nothing here may be imported by `core/` -
the dependency runs one way, which is what lets both shells share the rules.
"""
